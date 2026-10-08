# One repository per image this project actually builds (see each
# service's Dockerfile): the worker (which bundles the whole workspace,
# since it spawns the mock services as subprocesses - decision in
# docker/worker.Dockerfile) and the console. The three mock services and
# the scheduler aren't deployed as their own images - the worker already
# contains everything it needs to spawn them as subprocesses, and the
# scheduler/CLI runs from a developer's own machine (`pg run`, `pg
# replay`), not as a cluster workload.

resource "aws_ecr_repository" "worker" {
  name                 = "${var.cluster_name}/pg-worker"
  image_tag_mutability = "IMMUTABLE" # a tag is a specific build; overwriting one
  # silently would make "which image is actually running" unanswerable
  # from the tag alone - exactly the kind of non-determinism this
  # project's whole premise is about eliminating everywhere else.

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "console" {
  name                 = "${var.cluster_name}/console"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "worker" {
  repository = aws_ecr_repository.worker.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the last 20 images, expire the rest"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "console" {
  repository = aws_ecr_repository.console.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the last 20 images, expire the rest"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })
}
