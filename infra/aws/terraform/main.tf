# VPC and EKS control plane via the community modules (terraform-aws-
# modules), not hand-rolled: these two specifically handle a lot of
# correctness-sensitive plumbing (subnet tagging for the AWS LB
# controller/Cluster Autoscaler to discover them, the EKS OIDC provider,
# security group wiring between the control plane and nodes) that's easy
# to get subtly wrong by hand and has already been through far more
# real-world use than a first-pass custom version would see here. The
# project-specific pieces (S3, ECR, Secrets Manager, the worker's IRSA
# policy, KEDA) are plain resources below/in their own files, not hidden
# inside a module, since those ARE this project's own design.

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.8"

  name = "${var.cluster_name}-vpc"
  cidr = var.vpc_cidr

  azs             = slice(data.aws_availability_zones.available.names, 0, var.availability_zone_count)
  private_subnets = [for i in range(var.availability_zone_count) : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets  = [for i in range(var.availability_zone_count) : cidrsubnet(var.vpc_cidr, 4, i + 8)]

  enable_nat_gateway = true
  single_nat_gateway = true # one NAT for the whole VPC, not one per AZ - this cluster is not a
  # production service that needs per-AZ NAT redundancy; it scales to
  # zero between benchmark runs, and a single NAT gateway is the
  # single biggest fixed hourly cost this VPC has if it isn't shared.

  public_subnet_tags = {
    "kubernetes.io/role/elb"                    = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"           = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.24"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access = true # console/CLI access without a VPN - acceptable for a
  # benchmark-only cluster that scales to zero; a longer-lived
  # production deployment should set this false and go through a
  # bastion or VPN instead.

  enable_irsa = true

  eks_managed_node_groups = {
    system = {
      instance_types = var.system_node_instance_types
      capacity_type  = "ON_DEMAND"
      min_size       = var.system_node_desired_size
      max_size       = var.system_node_desired_size
      desired_size   = var.system_node_desired_size
      labels = {
        "proving-ground/role" = "system"
      }
    }
    workers = {
      instance_types = var.worker_node_instance_types
      capacity_type  = "SPOT"
      min_size       = var.worker_node_min_size
      max_size       = var.worker_node_max_size
      desired_size   = 0
      labels = {
        "proving-ground/role" = "worker"
      }
      taints = {
        worker = {
          key    = "proving-ground/role"
          value  = "worker"
          effect = "NO_SCHEDULE"
        }
      }
    }
  }

  tags = {
    Project = "proving-ground"
  }
}
