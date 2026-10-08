variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "proving-ground"
}

variable "cluster_version" {
  description = "Kubernetes version for the EKS control plane."
  type        = string
  default     = "1.31"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "availability_zone_count" {
  description = "Number of AZs to spread subnets across. 2 is the minimum EKS requires and keeps NAT gateway cost down (one per AZ) - this cluster scales to zero between benchmark runs, not a multi-AZ production service that needs 3 for quorum reasons."
  type        = number
  default     = 2
}

variable "system_node_instance_types" {
  description = "On-demand instance type(s) for the system node group - Postgres, ClickHouse, NATS, the console and the scheduler all run here, not on spot, since these are long-lived and a spot interruption here would take down the control plane mid-run, not just one simulation."
  type        = list(string)
  default     = ["t3.medium"]
}

variable "system_node_desired_size" {
  type    = number
  default = 2
}

variable "worker_node_instance_types" {
  description = "Spot instance type(s) for the worker node group - the spec's own 'worker fleet on autoscaling spot nodes'. Several types/sizes listed so the spot allocator has real substitutes available, not just one (a single instance type is the most common reason a spot node group can't get capacity in a given AZ)."
  type        = list(string)
  default     = ["m6i.large", "m5.large", "m6a.large"]
}

variable "worker_node_min_size" {
  description = "0 so the worker fleet genuinely scales to zero between runs (the spec's own 'Cost note') - KEDA's ScaledJob creates pods on demand; Cluster Autoscaler then has to add nodes to run them, which only works if min_size allows going to 0 first."
  type        = number
  default     = 0
}

variable "worker_node_max_size" {
  description = "Upper bound for the scale test in BENCHMARKS.md (1/4/16/64 workers) plus headroom."
  type        = number
  default     = 80
}

variable "tapes_bucket_name" {
  description = "S3 bucket for recorded tapes (pg_sdk.storage.BlobStore) - real S3 here, not SeaweedFS (SeaweedFS exists only to stand in for S3 locally without an AWS account; on AWS the platform talks to S3 directly)."
  type        = string
  default     = "proving-ground-tapes"
}

variable "snapshots_bucket_name" {
  description = "S3 bucket for environment template snapshots."
  type        = string
  default     = "proving-ground-snapshots"
}

variable "gemini_api_keys" {
  description = "Gemini API key(s) to seed into Secrets Manager (GEMINI_API_KEY, GEMINI_API_KEY2, ...). Left empty by default on purpose - real keys belong in a .tfvars file that is itself gitignored (see terraform.tfvars.example), never a literal default in version-controlled code."
  type        = list(string)
  default     = []
  sensitive   = true
}
