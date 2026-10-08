# KEDA, the same dependency the local cluster installs by hand before
# scripts/deploy_platform.sh (docs/MILESTONES.md, Milestone 6) - the
# worker ScaledJob's own prometheus-metric trigger (infra/k8s/local/
# platform/worker-scaledjob.yaml) is unchanged between local and AWS,
# so provisioning the operator here is the only AWS-specific piece.

resource "kubernetes_namespace" "keda" {
  metadata {
    name = "keda-system"
  }

  depends_on = [module.eks]
}

resource "helm_release" "keda" {
  name       = "keda"
  repository = "https://kedacore.github.io/charts"
  chart      = "keda"
  version    = "2.15.1"
  namespace  = kubernetes_namespace.keda.metadata[0].name
}
