output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "configure_kubectl" {
  description = "Run this once `terraform apply` has finished to point kubectl at the new cluster."
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}

output "tapes_bucket" {
  value = aws_s3_bucket.tapes.bucket
}

output "snapshots_bucket" {
  value = aws_s3_bucket.snapshots.bucket
}

output "worker_ecr_repository_url" {
  value = aws_ecr_repository.worker.repository_url
}

output "console_ecr_repository_url" {
  value = aws_ecr_repository.console.repository_url
}

output "worker_irsa_role_arn" {
  description = "Annotate the pg-worker ServiceAccount with eks.amazonaws.com/role-arn = this value."
  value       = module.worker_irsa_role.iam_role_arn
}

output "console_irsa_role_arn" {
  description = "Annotate the console ServiceAccount with eks.amazonaws.com/role-arn = this value."
  value       = module.console_irsa_role.iam_role_arn
}

output "gemini_api_keys_secret_arn" {
  value = aws_secretsmanager_secret.gemini_api_keys.arn
}

output "postgres_credentials_secret_arn" {
  value = aws_secretsmanager_secret.postgres_credentials.arn
}
