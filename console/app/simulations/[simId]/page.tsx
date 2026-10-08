import Link from "next/link";
import { notFound } from "next/navigation";
import { getSimulation } from "@/lib/postgres";
import { getCheckResults, getJudgeScore } from "@/lib/clickhouse";
import { getBlob, getManifest } from "@/lib/tape";
import { formatTimestamp } from "@/lib/format";
import { Mono } from "@/components/Mono";
import { Panel } from "@/components/Panel";
import { StatusBadge, simulationStateVariant } from "@/components/StatusBadge";
import type { StepKind } from "@/lib/types";

export const instant = false;
const STEP_KIND_STYLE: Record<StepKind, string> = {
  model: "text-accent-strong bg-accent-bg",
  tool: "text-warning bg-warning-bg",
  clock: "text-text-muted bg-neutral-bg",
};

function clockValue(blob: unknown): string | null {
  if (blob && typeof blob === "object" && "value" in blob) {
    return String((blob as { value: unknown }).value);
  }
  return null;
}

export default async function SimulationReplayPage({
  params,
}: {
  params: Promise<{ simId: string }>;
}) {
  const { simId } = await params;
  const sim = await getSimulation(simId);
  if (!sim) notFound();

  const [checks, judge, manifest] = await Promise.all([
    getCheckResults(simId),
    getJudgeScore(simId),
    getManifest(simId),
  ]);

  const blobCache = new Map<string, unknown>();
  if (manifest) {
    const hashes = new Set<string>();
    for (const step of manifest.steps) {
      hashes.add(step.input_hash);
      hashes.add(step.output_hash);
    }
    await Promise.all(
      Array.from(hashes).map(async (hash) => {
        blobCache.set(hash, await getBlob(hash));
      }),
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Link
          href={`/runs/${sim.run_id}`}
          className="text-xs text-text-faint hover:text-text-muted"
        >
          ← run {sim.run_id}
        </Link>
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-text">
            <Mono title={sim.id}>{sim.id}</Mono>
          </h1>
          <StatusBadge
            label={sim.state}
            variant={simulationStateVariant(sim.state)}
          />
          {sim.simulated_user && (
            <span className="rounded-md border border-border-muted px-1.5 py-0.5 text-[11px] text-text-faint">
              simulated user
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="flex flex-col gap-6 lg:col-span-2">
          <Panel
            title="Tape"
            description={
              manifest
                ? `${manifest.step_count} recorded steps`
                : "no tape recorded"
            }
          >
            {!manifest || manifest.steps.length === 0 ? (
              <div className="px-5 py-8 text-center text-sm text-text-faint">
                No steps recorded.
              </div>
            ) : (
              <ol className="divide-y divide-border-muted">
                {manifest.steps.map((step) => {
                  const clock =
                    step.kind === "clock"
                      ? clockValue(blobCache.get(step.output_hash))
                      : null;
                  return (
                    <li key={step.seq} className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <span className="w-8 shrink-0 text-right font-mono text-xs text-text-faint">
                          {step.seq}
                        </span>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide ${STEP_KIND_STYLE[step.kind]}`}
                        >
                          {step.kind}
                        </span>
                        <span className="font-mono text-sm text-text">
                          {step.name}
                        </span>
                        {clock && (
                          <span className="font-mono text-xs text-text-faint">
                            clock → {clock}
                          </span>
                        )}
                        <span className="ml-auto text-xs text-text-faint">
                          {formatTimestamp(step.recorded_at)}
                        </span>
                      </div>
                      {step.kind !== "clock" && (
                        <details className="mt-2 ml-11">
                          <summary className="cursor-pointer text-xs text-text-faint hover:text-text-muted">
                            view input / output
                          </summary>
                          <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
                            <pre className="max-h-64 overflow-auto rounded-md border border-border-muted bg-bg p-3 text-[11px] text-text-muted">
                              {JSON.stringify(
                                blobCache.get(step.input_hash),
                                null,
                                2,
                              )}
                            </pre>
                            <pre className="max-h-64 overflow-auto rounded-md border border-border-muted bg-bg p-3 text-[11px] text-text-muted">
                              {JSON.stringify(
                                blobCache.get(step.output_hash),
                                null,
                                2,
                              )}
                            </pre>
                          </div>
                        </details>
                      )}
                    </li>
                  );
                })}
              </ol>
            )}
          </Panel>
        </div>

        <div className="flex flex-col gap-6">
          <Panel title="Scenario">
            <div className="flex flex-col gap-3 px-5 py-4 text-sm">
              <div>
                <div className="text-xs text-text-faint">Persona</div>
                <div className="mt-0.5 text-text-muted">{sim.persona}</div>
              </div>
              <div>
                <div className="text-xs text-text-faint">Goal</div>
                <div className="mt-0.5 text-text-muted">{sim.goal}</div>
              </div>
              {sim.user_message && (
                <div>
                  <div className="text-xs text-text-faint">Opening message</div>
                  <div className="mt-0.5 text-text-muted">
                    {sim.user_message}
                  </div>
                </div>
              )}
              <div>
                <div className="text-xs text-text-faint">Seed</div>
                <div className="mt-0.5">
                  <Mono>{String(sim.seed)}</Mono>
                </div>
              </div>
            </div>
          </Panel>

          <Panel title="Result">
            <div className="flex flex-col gap-3 px-5 py-4 text-sm">
              {sim.result?.reply && (
                <div>
                  <div className="text-xs text-text-faint">Agent reply</div>
                  <div className="mt-0.5 text-text-muted">
                    {sim.result.reply}
                  </div>
                </div>
              )}
              {sim.result?.error && (
                <div>
                  <div className="text-xs text-text-faint">Error</div>
                  <div className="mt-0.5 text-danger">{sim.result.error}</div>
                </div>
              )}
            </div>
          </Panel>

          <Panel
            title="State checks"
            description={`${checks.filter((c) => c.passed).length}/${checks.length} passed`}
          >
            {checks.length === 0 ? (
              <div className="px-5 py-4 text-sm text-text-faint">
                No checks configured for this scenario.
              </div>
            ) : (
              <ul className="divide-y divide-border-muted text-sm">
                {checks.map((check) => (
                  <li
                    key={check.description}
                    className="flex items-start gap-2.5 px-5 py-3"
                  >
                    <span
                      className={`mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                        check.passed ? "bg-success" : "bg-danger"
                      }`}
                    />
                    <div>
                      <div className="text-text-muted">{check.description}</div>
                      <div className="mt-0.5 text-xs text-text-faint">
                        {check.detail}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Judge">
            {judge ? (
              <div className="flex flex-col gap-2 px-5 py-4 text-sm">
                <div className="flex items-center gap-2">
                  <StatusBadge
                    label={judge.resolved ? "resolved" : "unresolved"}
                    variant={judge.resolved ? "success" : "danger"}
                  />
                  <span className="text-text-muted">{judge.score}/5</span>
                </div>
                <div className="text-text-muted">{judge.rationale}</div>
                <div className="text-xs text-text-faint">
                  <Mono>{judge.model}</Mono>
                </div>
              </div>
            ) : (
              <div className="px-5 py-4 text-sm text-text-faint">
                Not judged yet.
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
