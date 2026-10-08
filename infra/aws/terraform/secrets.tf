# The spec's own "Secrets in AWS Secrets Manager; least-privilege IAM"
# requirement. One secret, one JSON blob with every GEMINI_API_KEY* the
# worker's own load_api_keys() already knows how to scan for
# (agents/reference_agent/src/reference_agent/agent.py) - so nothing
# about that function needs to change for AWS; only how the values reach
# the pod's environment does (the Helm chart's job, via External Secrets
# Operator or an init container - a Kubernetes-side concern, not
# Terraform's, so it isn't wired further here; see this directory's
# README).

resource "aws_secretsmanager_secret" "gemini_api_keys" {
  name        = "${var.cluster_name}/gemini-api-keys"
  description = "GEMINI_API_KEY* values for the reference agent's key rotation (agent.py's load_api_keys)."
}

resource "aws_secretsmanager_secret_version" "gemini_api_keys" {
  count     = length(var.gemini_api_keys) > 0 ? 1 : 0
  secret_id = aws_secretsmanager_secret.gemini_api_keys.id
  secret_string = jsonencode({
    for idx, key in var.gemini_api_keys :
    (idx == 0 ? "GEMINI_API_KEY" : "GEMINI_API_KEY${idx + 1}") => key
  })
}

resource "aws_secretsmanager_secret" "postgres_credentials" {
  name        = "${var.cluster_name}/postgres-credentials"
  description = "Metadata-store credentials (pg_sdk.postgres.connect_pool's PG_POSTGRES_DSN)."
}
