import boto3
import csv
import io
import json
import os

def lambda_handler(event, context):
    # Extract parameters from event and environment
    target_account_id = event.get('target_account_id')
    s3_bucket = event.get('s3_bucket')
    s3_rule_list_key = event.get('s3_rule_list_key')  # e.g., 'config/rules.json'
    aggregator_name = os.environ.get('AGGREGATOR_NAME')

    if not all([target_account_id, s3_bucket, s3_rule_list_key, aggregator_name]):
        raise ValueError("Missing required parameters: target_account_id, s3_bucket, s3_rule_list_key, or AGGREGATOR_NAME")

    # Step 1: Fetch the rule identifiers from the S3 JSON file
    s3_client = boto3.client('s3')
    try:
        response = s3_client.get_object(Bucket=s3_bucket, Key=s3_rule_list_key)
        rule_list_content = response['Body'].read().decode('utf-8')
        TARGET_CONFIG_RULE_IDENTIFIERS = json.loads(rule_list_content)
        if not isinstance(TARGET_CONFIG_RULE_IDENTIFIERS, list) or not all(isinstance(rule, str) for rule in TARGET_CONFIG_RULE_IDENTIFIERS):
            raise ValueError("S3 JSON file must contain a list of strings")
    except Exception as e:
        raise Exception(f"Failed to load or parse rule list from s3://{s3_bucket}/{s3_rule_list_key}: {str(e)}")

    config_client = boto3.client('config')

    # Step 2: Get compliance status for rules in the specified account using aggregator
    rule_statuses = []
    next_token = None
    while True:
        api_params = {
            'ConfigurationAggregatorName': aggregator_name,
            'Filters': {'AccountId': target_account_id}
        }
        if next_token:
            api_params['NextToken'] = next_token

        response = config_client.describe_aggregate_compliance_by_config_rules(**api_params)
        
        for rule in response.get('AggregateComplianceByConfigRules', []):
            api_rule_name = rule['ConfigRuleName']
            for target_identifier in TARGET_CONFIG_RULE_IDENTIFIERS:
                if target_identifier in api_rule_name:  # Substring match
                    compliance = rule.get('Compliance', {})
                    contributor_count = compliance.get('ComplianceContributorCount', {}).get('CappedCount', 0)
                    rule_statuses.append({
                        'AccountID': rule['AccountId'],
                        'AwsRegion': rule['AwsRegion'],
                        'ConfigRuleName': api_rule_name,
                        'ComplianceType': compliance.get('ComplianceType', 'N/A'),
                        'NonCompliantResourceCount': contributor_count if compliance.get('ComplianceType') == 'NON_COMPLIANT' else 0,
                        'Note': 'Contributor count is the number of non-compliant resources (capped at 100)' if contributor_count > 0 else ''
                    })
                    break  # Found a match, move to next rule

        next_token = response.get('NextToken')
        if not next_token:
            break

    # Step 3: Add NOT_FOUND entries for any target rules not in the results
    found_rules = {rule['ConfigRuleName'] for rule in rule_statuses}
    for target_identifier in TARGET_CONFIG_RULE_IDENTIFIERS:
        if not any(target_identifier in rule_name for rule_name in found_rules):
            rule_statuses.append({
                'AccountID': target_account_id,
                'AwsRegion': 'N/A',
                'ConfigRuleName': target_identifier,
                'ComplianceType': 'NOT_FOUND',
                'NonCompliantResourceCount': 0,
                'Note': 'Rule not found in aggregator results'
            })

    # Step 4: Export to CSV and upload to S3
    if rule_statuses:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            'AccountID', 'AwsRegion', 'ConfigRuleName', 'ComplianceType',
            'NonCompliantResourceCount', 'Note'
        ])
        writer.writeheader()
        writer.writerows(rule_statuses)
        csv_content = output.getvalue().encode('utf-8')

        s3_key = f'config_rule_compliance_{target_account_id}.csv'
        s3_client.put_object(Body=csv_content, Bucket=s3_bucket, Key=s3_key)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'CSV uploaded to s3://{s3_bucket}/{s3_key}',
                'results': rule_statuses
            })
        }
    else:
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'No results found'})
        }