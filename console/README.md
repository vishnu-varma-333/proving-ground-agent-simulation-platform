# Proving Ground Console

Run explorer, step-by-step replay viewer, and version comparison for
Proving Ground simulations. Reads live from the same Postgres,
ClickHouse and S3-compatible object storage the platform already
writes to - read-only, no separate API service (see `DECISIONS.md` at
the repo root, Milestone 9).

## Running locally

Requires the local cluster to be up (`scripts/up.sh` at the repo
root). `.env.local` already points at its default host ports:

```bash
npm install
npm run dev
```

Opens on http://localhost:3000.

## Pages

- `/` - every run, newest first, with pass/fail/pending counts.
- `/runs/[runId]` - a run's simulations, each scenario's checks and
  judge score.
- `/simulations/[simId]` - the full recorded tape for one simulation:
  every model, tool and clock step in order, with the simulated
  clock's value shown inline for clock reads, and each step's full
  recorded input/output available to expand.
- `/compare?a=<runId>&b=<runId>` - two runs of the same suite,
  scenario by scenario, flagging which ones changed outcome.
