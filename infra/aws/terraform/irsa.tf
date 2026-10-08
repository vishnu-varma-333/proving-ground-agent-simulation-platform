# Least-privilege IAM for the worker pod specifically: read/write on the
# two S3 buckets it actually touches (pg_sdk.storage.BlobStore) and
# read-only on the two secrets it needs - not an AWS-account-wide S3 or
# Secrets Manager grant, and not shared with the console's own (narrower,
# read-only) role below.

data "aws_iam_policy_document" "worker_s3" {
  statement {
    sid    = "TapesAndSnapshotsReadWrite"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:HeadObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.tapes.arn,
      "${aws_s3_bucket.tapes.arn}/*",
      aws_s3_bucket.snapshots.arn,
      "${aws_s3_bucket.snapshots.arn}/*",
    ]
  }
}

data "aws_iam_policy_document" "worker_secrets" {
  statement {
    sid    = "ReadGeminiKeys"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
    ]
    resources = [
      aws_secretsmanager_secret.gemini_api_keys.arn,
      aws_secretsmanager_secret.postgres_credentials.arn,
    ]
  }
}

resource "aws_iam_policy" "worker" {
  name   = "${var.cluster_name}-worker"
  policy = data.aws_iam_policy_document.worker_s3.json
}

resource "aws_iam_policy" "worker_secrets" {
  name   = "${var.cluster_name}-worker-secrets"
  policy = data.aws_iam_policy_document.worker_secrets.json
}

module "worker_irsa_role" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.44"

  role_name = "${var.cluster_name}-worker"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["proving-ground:pg-worker"]
    }
  }
}

resource "aws_iam_role_policy_attachment" "worker_s3" {
  role       = module.worker_irsa_role.iam_role_name
  policy_arn = aws_iam_policy.worker.arn
}

resource "aws_iam_role_policy_attachment" "worker_secrets" {
  role       = module.worker_irsa_role.iam_role_name
  policy_arn = aws_iam_policy.worker_secrets.arn
}

# The console only ever reads - no PutObject, no secrets access at all
# (its own Postgres/ClickHouse credentials are narrower-scoped
# application secrets, not AWS IAM, same as locally).
data "aws_iam_policy_document" "console_s3_read" {
  statement {
    sid    = "TapesReadOnly"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.tapes.arn,
      "${aws_s3_bucket.tapes.arn}/*",
    ]
  }
}

resource "aws_iam_policy" "console_s3_read" {
  name   = "${var.cluster_name}-console-s3-read"
  policy = data.aws_iam_policy_document.console_s3_read.json
}

module "console_irsa_role" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.44"

  role_name = "${var.cluster_name}-console"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["proving-ground:console"]
    }
  }
}

resource "aws_iam_role_policy_attachment" "console_s3_read" {
  role       = module.console_irsa_role.iam_role_name
  policy_arn = aws_iam_policy.console_s3_read.arn
}
