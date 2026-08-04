# Project rules

Use AWS profile: cockroach-hackathon-dev
Use AWS region: eu-central-1

All application and infrastructure changes must be made in the repository first.

Never:
- use the AWS root account
- print or store AWS credentials
- commit .env files or secrets
- delete AWS resources without explicit approval
- deploy without showing the planned changes
- make permanent manual changes directly in AWS

Before every deployment:
- run tests
- validate the SAM template
- show git diff
- show which AWS resources will be created or updated
- request approval

Temporary read-only diagnostic commands are allowed.
Use least-privilege IAM roles for deployed workloads.