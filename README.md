# aws-config-rule-audit-lambda
aws-config-rule-audit-lambda is a serverless AWS Lambda function that monitors AWS Config rule compliance across accounts in an organization using a config aggregator. It retrieves a list of target rules from an S3-hosted JSON file, checks their compliance status, and exports results to a CSV in S3. Built with Python, Boto3, and CloudFormation.
