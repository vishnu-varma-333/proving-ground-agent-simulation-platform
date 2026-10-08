export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatDuration(
  startIso: string | null,
  endIso: string | null,
): string {
  if (!startIso || !endIso) return "—";
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function truncateId(id: string, keep = 10): string {
  if (id.length <= keep + 3) return id;
  return `${id.slice(0, keep)}…`;
}

export function truncateHash(hash: string, keep = 8): string {
  if (hash.length <= keep) return hash;
  return `${hash.slice(0, keep)}…`;
}
