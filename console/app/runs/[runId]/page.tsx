import Link from "next/link";
import { notFound } from "next/navigation";
import { getRun, listSimulationsForRun } from "@/lib/postgres";
import {
  getCheckResultsForSims,
  getJudgeScoresForSims,
} from "@/lib/clickhouse";
import { formatDuration, formatTimestamp } from "@/lib/format";
import { Mono } from "@/components/Mono";
import { Panel } from "@/components/Panel";
import {
  StatusBadge,
  runStatusVariant,
  simulationStateVariant,
} from "@/components/StatusBadge";

export const instant = false;

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  const run = await getRun(runId);
  if (!run) notFound();

  const simulations = await listSimulationsForRun(runId);
  const simIds = simulations.map((s) => s.id);
  const [checksBySim, judgeBySim] = await Promise.all([
    getCheckResultsForSims(simIds),
    getJudgeScoresForSims(simIds),
  ]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Link
          href="/"
          className="text-xs text-text-faint hover:text-text-muted"
        >
          ← all runs
        </Link>
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-text">
            <Mono title={run.id}>{run.id}</Mono>
          </h1>
          <StatusBadge
            label={run.status}
            variant={runStatusVariant(run.status)}
          />
        </div>
        <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-text-faint">Suite</dt>
            <dd className="mt-0.5 text-text-muted">{run.suite_name}</dd>
          </div>
          <div>
            <dt className="text-xs text-text-faint">Agent version</dt>
            <dd className="mt-0.5">
              <Mono title={run.agent_version_id}>{run.agent_version_id}</Mono>
            </dd>
          </div>
          <div>
            <dt className="text-xs text-text-faint">Started</dt>
            <dd className="mt-0.5 text-text-muted">
              {formatTimestamp(run.started_at)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-text-faint">Duration</dt>
            <dd className="mt-0.5 text-text-muted">
              {formatDuration(run.started_at, run.finished_at)}
            </dd>
          </div>
        </dl>
      </div>

      <Panel
        title="Simulations"
        description={`${run.completed} ok · ${run.failed} failed · ${run.pending} in progress`}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border-muted text-xs text-text-faint">
                <th className="px-5 py-3 font-medium">Simulation</th>
                <th className="px-5 py-3 font-medium">Scenario</th>
                <th className="px-5 py-3 font-medium">State</th>
                <th className="px-5 py-3 font-medium">Checks</th>
                <th className="px-5 py-3 font-medium">Judge</th>
              </tr>
            </thead>
            <tbody>
              {simulations.map((sim) => {
                const checks = checksBySim.get(sim.id) ?? [];
                const checksPassed = checks.filter((c) => c.passed).length;
                const judge = judgeBySim.get(sim.id);
                const isFailed = sim.state === "failed";
                return (
                  <tr
                    key={sim.id}
                    className={`border-b border-border-muted last:border-0 transition-colors hover:bg-bg-hover ${
                      isFailed ? "bg-danger-bg/40" : ""
                    }`}
                  >
                    <td className="px-5 py-3">
                      <Link
                        href={`/simulations/${sim.id}`}
                        className="hover:text-accent-strong"
                      >
                        <Mono title={sim.id}>{sim.id}</Mono>
                      </Link>
                    </td>
                    <td className="px-5 py-3">
                      <div className="text-text-muted">{sim.scenario_id}</div>
                      <div className="mt-0.5 text-xs text-text-faint">
                        {sim.goal}
                      </div>
                    </td>
                    <td className="px-5 py-3">
                      <StatusBadge
                        label={sim.state}
                        variant={simulationStateVariant(sim.state)}
                      />
                    </td>
                    <td className="px-5 py-3 text-text-muted">
                      {checks.length > 0 ? (
                        <span
                          className={
                            checksPassed === checks.length
                              ? "text-success"
                              : "text-danger"
                          }
                        >
                          {checksPassed}/{checks.length}
                        </span>
                      ) : (
                        <span className="text-text-faint">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-text-muted">
                      {judge ? (
                        <span
                          className={
                            judge.resolved ? "text-success" : "text-danger"
                          }
                        >
                          {judge.score}/5
                        </span>
                      ) : (
                        <span className="text-text-faint">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
