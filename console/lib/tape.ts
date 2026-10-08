// Reads the same content-addressed tape pg_sdk.storage.BlobStore writes
// (decision 11): a per-simulation manifest listing steps in order, plus
// blobs keyed by sha256 of their own bytes. This is a reader only - the
// console never writes to the tape store.
import { GetObjectCommand, S3Client } from "@aws-sdk/client-s3";
import type { TapeManifest } from "./types";

let client: S3Client | null = null;

function getClient(): S3Client {
  if (!client) {
    client = new S3Client({
      endpoint: process.env.PG_S3_ENDPOINT_URL ?? "http://127.0.0.1:29001",
      region: process.env.PG_S3_REGION ?? "us-east-1",
      credentials: {
        accessKeyId: process.env.PG_S3_ACCESS_KEY_ID ?? "proving_ground",
        secretAccessKey:
          process.env.PG_S3_SECRET_ACCESS_KEY ?? "proving-ground-local-dev",
      },
      forcePathStyle: true,
    });
  }
  return client;
}

const BUCKET = process.env.PG_S3_BUCKET ?? "proving-ground-tapes";

async function getObjectJson<T>(key: string): Promise<T | null> {
  try {
    const res = await getClient().send(
      new GetObjectCommand({ Bucket: BUCKET, Key: key }),
    );
    const body = await res.Body?.transformToString();
    return body ? (JSON.parse(body) as T) : null;
  } catch (err: unknown) {
    const name = (err as { name?: string })?.name;
    if (name === "NoSuchKey" || name === "NotFound") return null;
    throw err;
  }
}

export async function getManifest(simId: string): Promise<TapeManifest | null> {
  return getObjectJson<TapeManifest>(`runs/${simId}/manifest.json`);
}

export async function getBlob(hash: string): Promise<unknown | null> {
  return getObjectJson(`blobs/sha256/${hash.slice(0, 2)}/${hash}.json`);
}
