# Infrastructure

Terraform for the AWS pieces, added in stage 5. Deliberately minimal — the point is to
demonstrate infrastructure-as-code and a reproducible deploy, not to build a platform.

Planned: an ECS service or Lambda for the API, RDS Postgres with pgvector, S3 for the
corpus and eval artifacts, Secrets Manager for the API key, and a budget alarm.

Put the monthly cost estimate in this file once it exists. A portfolio project that knows
what it costs to run reads differently from one that does not.
