# Terraform for all AWS resources (the spec's own "Deployment" requirement
# under Production readiness) - genuine, reviewable infrastructure-as-code.
# NOT applied in this session: no AWS account/credentials were provided
# for this project, and provisioning real EKS + spot capacity costs real
# money, which this project's own working rules treat as something to
# confirm with the project owner first, not decide alone. See
# DECISIONS.md (Milestone 10) and README.md in this directory for exactly
# what that means for this code's current state.

terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.31"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.14"
    }
  }

  # Local backend by default so this plans/applies without any prior setup.
  # A real deployment should move state to S3 + DynamoDB locking before
  # the first apply (two people running `terraform apply` against local
  # state is how state files get clobbered) - left as a backend block any
  # user can uncomment once they've created that bucket/table themselves,
  # rather than this config assuming infrastructure it can't yet see:
  #
  # backend "s3" {
  #   bucket         = "proving-ground-terraform-state"
  #   key            = "proving-ground/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "proving-ground-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "proving-ground"
      ManagedBy = "terraform"
    }
  }
}

data "aws_eks_cluster_auth" "this" {
  name = module.eks.cluster_name
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.this.token
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    token                  = data.aws_eks_cluster_auth.this.token
  }
}
