// Same raw-HTTP approach as pg_sdk.clickhouse.ClickHouseClient (decision
// 27): no dedicated driver, just POST to ClickHouse's own HTTP interface
// and parse JSONEachRow - consistent between the Python and TypeScript
// sides rather than picking a different client library per language.
import type { CheckResultRow, JudgeScoreRow } from "./types";

function config() {
  return {
    url: process.env.CLICKHOUSE_URL ?? "http://localhost:28123",
    database: process.env.CLICKHOUSE_DB ?? "proving_ground",
    user: process.env.CLICKHOUSE_USER ?? "proving_ground",
    password: process.env.CLICKHOUSE_PASSWORD ?? "proving-ground-local-dev",
  };
}

async function chQuery<T>(query: string): Promise<T[]> {
  const { url, database, user, password } = config();
  const params = new URLSearchParams({
    database,
    query: `${query} FORMAT JSONEachRow`,
  });
  const res = await fetch(`${url}/?${params.toString()}`, {
    method: "POST",
    headers: {
      Authorization: `Basic ${Buffer.from(`${user}:${password}`).toString("base64")}`,
    },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(
      `ClickHouse query failed (${res.status}): ${await res.text()}`,
    );
  }
  const text = await res.text();
  if (!text.trim()) return [];
  return text
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as T);
}

function quoteList(ids: string[]): string {
  return ids.map((id) => `'${id.replace(/'/g, "\\'")}'`).join(", ");
}

export async function getCheckResultsForSims(
  simIds: string[],
): Promise<Map<string, CheckResultRow[]>> {
  const map = new Map<string, CheckResultRow[]>();
  if (simIds.length === 0) return map;
  const rows = await chQuery<CheckResultRow>(
    `SELECT sim_id, description, service, passed, detail, recorded_at
     FROM check_results WHERE sim_id IN (${quoteList(simIds)}) ORDER BY description`,
  );
  for (const row of rows) {
    const list = map.get(row.sim_id) ?? [];
    list.push(row);
    map.set(row.sim_id, list);
  }
  return map;
}

export async function getJudgeScoresForSims(
  simIds: string[],
): Promise<Map<string, JudgeScoreRow>> {
  const map = new Map<string, JudgeScoreRow>();
  if (simIds.length === 0) return map;
  const rows = await chQuery<JudgeScoreRow>(
    `SELECT sim_id, resolved, score, rationale, model, recorded_at
     FROM judge_scores WHERE sim_id IN (${quoteList(simIds)}) ORDER BY recorded_at DESC`,
  );
  for (const row of rows) {
    if (!map.has(row.sim_id)) map.set(row.sim_id, row);
  }
  return map;
}

export async function getCheckResults(
  simId: string,
): Promise<CheckResultRow[]> {
  const map = await getCheckResultsForSims([simId]);
  return map.get(simId) ?? [];
}

export async function getJudgeScore(
  simId: string,
): Promise<JudgeScoreRow | null> {
  const map = await getJudgeScoresForSims([simId]);
  return map.get(simId) ?? null;
}
