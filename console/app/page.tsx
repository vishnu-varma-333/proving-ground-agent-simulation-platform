import Link from "next/link";
import { listRuns } from "@/lib/postgres";
import { formatDuration, formatTimestamp } from "@/lib/format";
import { Mono } from "@/components/Mono";
import { Panel } from "@/components/Panel";
import { StatusBadge, runStatusVariant } from "@/components/StatusBadge";

export const instant = false;

export default async function RunExplorerPage() {
  const runs = await listRuns();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold text-text">Runs</h1>
        <p className="mt-1 text-sm text-text-faint">
          Every suite run against the reference agent, newest first.
        </p>
      </div>

      <Panel>
        {runs.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-text-faint">
            No runs yet — submit a suite with <Mono>pg run suite.yaml</Mono>.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border-muted text-xs text-text-faint">
                  <th className="px-5 py-3 font-medium">Run</th>
                  <th className="px-5 py-3 font-medium">Suite</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Simulations</th>
                  <th className="px-5 py-3 font-medium">Started</th>
                  <th className="px-5 py-3 font-medium">Duration</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.id}
                    className="border-b border-border-muted last:border-0 transition-colors hover:bg-bg-hover"
                  >
                    <td className="px-5 py-3">
                      <Link
                        href={`/runs/${run.id}`}
                        className="hover:text-accent-strong"
                      >
                        <Mono title={run.id}>{run.id}</Mono>
                      </Link>
                    </td>
                    <td className="px-5 py-3 text-text-muted">
                      {run.suite_name}
                    </td>
                    <td className="px-5 py-3">
                      <StatusBadge
                        label={run.status}
                        variant={runStatusVariant(run.status)}
                      />
                    </td>
                    <td className="px-5 py-3 text-text-muted">
                      <span className="text-success">{run.completed}</span>
                      {" / "}
                      <span
                        className={
                          run.failed > 0 ? "text-danger" : "text-text-faint"
                        }
                      >
                        {run.failed}
                      </span>
                      {" / "}
                      <span className="text-text-faint">{run.total}</span>
                      <span className="ml-1.5 text-xs text-text-faint">
                        ok / failed / total
                      </span>
                    </td>
                    <td className="px-5 py-3 text-text-muted">
                      {formatTimestamp(run.started_at)}
                    </td>
                    <td className="px-5 py-3 text-text-muted">
                      {formatDuration(run.started_at, run.finished_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
