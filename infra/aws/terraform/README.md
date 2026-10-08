# AWS deployment (Terraform)

Real, reviewable infrastructure-as-code for the spec's own Milestone 10
requirement - "AWS deploy on spot nodes" - but **not applied**. No AWS
account or credentials were provided for this project, and provisioning
a real EKS cluster plus spot capacity costs real money and is hard to
walk back cleanly, which this project's own working rules treat as
something to confirm with the project owner first rather than decide
alone. See `DECISIONS.md` (Milestone 10) for the full reasoning.

## What this provisions

- A VPC (2 AZs by default, one shared NAT gateway) and an EKS cluster,
  via the `terraform-aws-modules` community modules.
- Two managed node groups: `system` (on-demand - Postgres, ClickHouse,
  NATS, the console, the scheduler) and `workers` (spot, 0 desired,
  scales with KEDA/Cluster Autoscaler - the spec's "worker fleet on
  autoscaling spot nodes" and "scales to zero between runs").
- Two S3 buckets (tapes, snapshots) - real S3, replacing local
  development's SeaweedFS stand-in.
- Two ECR repositories (worker, console) with immutable tags and a
  20-image retention policy.
- Two Secrets Manager secrets (Gemini API keys, Postgres credentials)
  and two IRSA roles (`worker`, `console`) scoped to exactly the
  buckets/secrets each one actually needs - the console's role has no
  write access and no secrets access at all.
- KEDA, installed via its own Helm chart (matching what the local
  cluster installs by hand before `scripts/deploy_platform.sh`).

## What this deliberately does NOT provision

- **The platform's own services** (Postgres, ClickHouse, NATS, the
  console, the worker ScaledJob) - those are the Helm chart's job
  (`infra/aws/helm/`), applied against this cluster once it exists, the
  same split local development already has between `scripts/up.sh`
  (infra) and `scripts/deploy_platform.sh` (the platform on top of it).
- **Getting secrets from Secrets Manager into a pod's environment** -
  a Kubernetes-side concern (External Secrets Operator syncing into a
  `Secret`, or an init container calling `GetSecretValue` directly),
  deliberately left to the Helm chart rather than half-wired here.
- **Network egress restricted to "approved model endpoints"** (a
  Production readiness requirement in the spec). A security-group rule
  can restrict egress by port, not by domain - actually enforcing
  "only `generativelanguage.googleapis.com`" needs something
  DNS/TLS-aware in the path, like AWS Network Firewall's domain
  filtering, which is itself a separate, non-trivial piece of
  infrastructure with its own real cost. Named here as a known,
  specific gap rather than approximated with a rule that wouldn't
  actually satisfy what it claims to.
- **A remote Terraform state backend** - `versions.tf` has a
  commented-out `backend "s3"` block; using it means creating that
  bucket/table first (outside Terraform, the usual chicken-and-egg for
  a state backend), which isn't done here since nothing has been
  applied yet to need shared state.

## Before a real `terraform apply`

1. `cp terraform.tfvars.example terraform.tfvars` and fill in real
   values (`terraform.tfvars` is gitignored).
2. Decide on the state backend (local is fine for a single operator;
   uncomment the `backend "s3"` block in `versions.tf` once that
   bucket/table exist for anyone else).
3. `terraform init && terraform validate && terraform plan` - read the
   plan before applying anything that costs money.
4. After `apply`: `$(terraform output -raw configure_kubectl)`, then
   deploy the Helm chart (`infra/aws/helm/`).
