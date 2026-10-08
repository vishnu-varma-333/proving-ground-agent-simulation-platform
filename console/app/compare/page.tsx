import { getRun, listRuns, listSimulationsForRun } from "@/lib/postgres";
import {
  getCheckResultsForSims,
  getJudgeScoresForSims,
} from "@/lib/clickhouse";
import { Panel } from "@/components/Panel";
import { StatusBadge, simulationStateVariant } from "@/components/StatusBadge";
import type { RunRow, SimulationRow } from "@/lib/types";

export const instant = false;
function RunPicker({
  name,
  runs,
  selected,
}: {
  name: string;
  runs: RunRow[];
  selected?: string;
}) {
  return (
    <select
      name={name}
      defaultValue={selected ?? ""}
      className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-text [color-scheme:dark]"
    >
      <option value="" disabled>
        Select a run…
      </option>
      {runs.map((run) => (
        <option key={run.id} value={run.id}>
          {run.suite_name} · {run.id} · {run.status}
        </option>
      ))}
    </select>
  );
}

type Side = { run: RunRow; simsByScenario: Map<string, SimulationRow> };

async function loadSide(runId: string): Promise<Side | null> {
  const run = await getRun(runId);
  if (!run) return null;
  const sims = await listSimulationsForRun(runId);
  return { run, simsByScenario: new Map(sims.map((s) => [s.scenario_id, s])) };
}

function outcomeLabel(
  sim: SimulationRow | undefined,
  checksOk: boolean | null,
  judgeOk: boolean | null,
) {
  if (!sim) return { label: "missing", variant: "neutral" as const };
  if (sim.state !== "completed")
    return { label: sim.state, variant: simulationStateVariant(sim.state) };
  if (checksOk === false || judgeOk === false)
    return { label: "regressed", variant: "danger" as const };
  return { label: "ok", variant: "success" as const };
}

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ a?: string; b?: string }>;
}) {
  const { a, b } = await searchParams;
  const runs = await listRuns(100);

  const [sideA, sideB] = await Promise.all([
    a ? loadSide(a) : null,
    b ? loadSide(b) : null,
  ]);

  let rows: Array<{
    scenarioId: string;
    simA?: SimulationRow;
    simB?: SimulationRow;
    checksA: boolean | null;
    checksB: boolean | null;
    judgeA: boolean | null;
    judgeB: boolean | null;
  }> = [];

  if (sideA && sideB) {
    const scenarioIds = new Set([
      ...sideA.simsByScenario.keys(),
      ...sideB.simsByScenario.keys(),
    ]);
    const simA = Array.from(sideA.simsByScenario.values());
    const simB = Array.from(sideB.simsByScenario.values());
    const [checksA, checksB, judgeA, judgeB] = await Promise.all([
      getCheckResultsForSims(simA.map((s) => s.id)),
      getCheckResultsForSims(simB.map((s) => s.id)),
      getJudgeScoresForSims(simA.map((s) => s.id)),
      getJudgeScoresForSims(simB.map((s) => s.id)),
    ]);

    rows = Array.from(scenarioIds)
      .sort()
      .map((scenarioId) => {
        const simA = sideA.simsByScenario.get(scenarioId);
        const simB = sideB.simsByScenario.get(scenarioId);
        const checksOkA = simA
          ? (checksA.get(simA.id)?.every((c) => c.passed) ?? null)
          : null;
        const checksOkB = simB
          ? (checksB.get(simB.id)?.every((c) => c.passed) ?? null)
          : null;
        const judgeRowA = simA ? judgeA.get(simA.id) : undefined;
        const judgeRowB = simB ? judgeB.get(simB.id) : undefined;
        const judgeOkA = judgeRowA ? judgeRowA.resolved === 1 : null;
        const judgeOkB = judgeRowB ? judgeRowB.resolved === 1 : null;
        return {
          scenarioId,
          simA,
          simB,
          checksA: checksOkA,
          checksB: checksOkB,
          judgeA: judgeOkA,
          judgeB: judgeOkB,
        };
      });
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold text-text">Compare runs</h1>
        <p className="mt-1 text-sm text-text-faint">
          Pick two runs of the same suite to see which scenarios changed
          outcome.
        </p>
      </div>

      <Panel>
        <form
          method="get"
          className="flex flex-col gap-4 px-5 py-5 sm:flex-row sm:items-end"
        >
          <div className="flex-1">
            <label className="mb-1.5 block text-xs text-text-faint">
              Run A
            </label>
            <RunPicker name="a" runs={runs} selected={a} />
          </div>
          <div className="flex-1">
            <label className="mb-1.5 block text-xs text-text-faint">
              Run B
            </label>
            <RunPicker name="b" runs={runs} selected={b} />
          </div>
          <button
            type="submit"
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-bg transition-opacity hover:opacity-90"
          >
            Compare
          </button>
        </form>
      </Panel>

      {sideA && sideB && (
        <Panel
          title={`${sideA.run.suite_name}: ${sideA.run.id} vs ${sideB.run.id}`}
          description={`${sideA.run.agent_version_id} vs ${sideB.run.agent_version_id}`}
        >
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border-muted text-xs text-text-faint">
                  <th className="px-5 py-3 font-medium">Scenario</th>
                  <th className="px-5 py-3 font-medium">Run A</th>
                  <th className="px-5 py-3 font-medium">Run B</th>
                  <th className="px-5 py-3 font-medium">Changed</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const outcomeA = outcomeLabel(
                    row.simA,
                    row.checksA,
                    row.judgeA,
                  );
                  const outcomeB = outcomeLabel(
                    row.simB,
                    row.checksB,
                    row.judgeB,
                  );
                  const changed = outcomeA.label !== outcomeB.label;
                  return (
                    <tr
                      key={row.scenarioId}
                      className={`border-b border-border-muted last:border-0 ${
                        changed ? "bg-warning-bg/30" : ""
                      }`}
                    >
                      <td className="px-5 py-3 text-text-muted">
                        {row.scenarioId}
                      </td>
                      <td className="px-5 py-3">
                        <StatusBadge
                          label={outcomeA.label}
                          variant={outcomeA.variant}
                        />
                      </td>
                      <td className="px-5 py-3">
                        <StatusBadge
                          label={outcomeB.label}
                          variant={outcomeB.variant}
                        />
                      </td>
                      <td className="px-5 py-3">
                        {changed ? (
                          <span className="text-warning">yes</span>
                        ) : (
                          <span className="text-text-faint">no</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {(a || b) && (!sideA || !sideB) && (
        <p className="text-sm text-danger">
          One or both selected runs could not be found.
        </p>
      )}
    </div>
  );
}
