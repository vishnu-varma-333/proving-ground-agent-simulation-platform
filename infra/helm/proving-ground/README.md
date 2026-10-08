# proving-ground (Helm chart)

The spec's own "Helm chart for services" - Postgres, ClickHouse, NATS
JetStream, object storage (SeaweedFS locally, disabled on AWS in favor
of real S3), the console, the worker fleet (KEDA `ScaledJob`), the
metrics exporter, and Prometheus/Grafana. One chart, two values files:
`values.yaml` matches `infra/k8s/local`'s own hand-applied manifests
exactly; `values-aws.yaml` overrides only what genuinely differs on the
EKS cluster `infra/aws/terraform` provisions (real S3, IRSA role
annotations, spot-node-group taint tolerations, a `LoadBalancer`
console service).

## Local (against kind)

```bash
helm install proving-ground . -n proving-ground --create-namespace
```

Requires KEDA already installed (`helm install keda kedacore/keda -n
keda-system --create-namespace`) and the worker/console images
available to the cluster - `scripts/up.sh`'s own pull-through registry
pattern for local image builds (see DECISIONS.md, decision 5).

## AWS (against the EKS cluster `infra/aws/terraform` provisions)

```bash
helm install proving-ground . -n proving-ground --create-namespace \
  -f values-aws.yaml \
  --set images.worker=$(terraform -chdir=../terraform output -raw worker_ecr_repository_url):latest \
  --set images.console=$(terraform -chdir=../terraform output -raw console_ecr_repository_url):latest \
  --set worker.serviceAccount.roleArn=$(terraform -chdir=../terraform output -raw worker_irsa_role_arn) \
  --set console.serviceAccount.roleArn=$(terraform -chdir=../terraform output -raw console_irsa_role_arn)
```

`worker-api-keys` (the Gemini keys) isn't set via `--set` on the
command line on purpose - populate it the same way
`scripts/deploy_platform.sh` does locally (imperative `kubectl create
secret` from a file that's never committed) or via an External Secrets
Operator synced from the Secrets Manager secret `infra/aws/terraform/
secrets.tf` creates, not as a Helm value that would end up in release
history.

## Validated, not yet applied to a real cluster end-to-end

`helm lint` and `helm template` both pass clean (see DECISIONS.md,
Milestone 10) and `helm install --dry-run` against the real local kind
cluster renders every resource without error. A full `helm install`
onto kind (replacing the hand-applied manifests this session actually
used throughout Milestones 1-9) and the AWS path specifically have not
been exercised live in this session - the former because the running
cluster already has this project's real data on it and swapping its
management to Helm mid-session risked that data for a verification
step that `--dry-run` already covers just as honestly; the latter for
the same reason the rest of `infra/aws/terraform` hasn't been applied
(see that directory's own README).
