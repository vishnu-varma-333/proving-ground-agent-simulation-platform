# Real S3 (not SeaweedFS - that only exists to stand in for S3 locally
# without an AWS account). Same two buckets the local SeaweedFS setup
# creates (infra/k8s/local/base/object-storage.yaml's bootstrap Job):
# tapes (pg_sdk.storage.BlobStore's content-addressed blobs/manifests)
# and snapshots (environment template forks, Milestone 7).

resource "aws_s3_bucket" "tapes" {
  bucket = var.tapes_bucket_name
}

resource "aws_s3_bucket_versioning" "tapes" {
  bucket = aws_s3_bucket.tapes.id
  versioning_configuration {
    status = "Disabled" # content-addressed by hash already - a second object
    # version of the same key would only happen if two different byte
    # strings somehow hashed to the same digest, which is exactly the
    # property content-addressing is supposed to rule out.
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tapes" {
  bucket = aws_s3_bucket.tapes.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tapes" {
  bucket                  = aws_s3_bucket.tapes.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "snapshots" {
  bucket = var.snapshots_bucket_name
}

resource "aws_s3_bucket_server_side_encryption_configuration" "snapshots" {
  bucket = aws_s3_bucket.snapshots.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "snapshots" {
  bucket                  = aws_s3_bucket.snapshots.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
