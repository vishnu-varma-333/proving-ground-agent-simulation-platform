# Proving Ground

A distributed, deterministic simulation engine that runs thousands of
realistic scenarios against an AI agent before release and replays any
failure exactly.

AI agents are non-deterministic and talk to real tools and real users, so
teams can't reliably test them: bugs appear only in production, can't be
reproduced, and multi-day workflows are impossible to test quickly. Proving
Ground runs scenarios in parallel across a worker fleet, records every
model response, tool response and clock reading so any run replays exactly,
and drives simulations on a virtual clock so a three-day scenario finishes
in seconds.

Deterministic simulation testing — the technique behind famously reliable
databases — applied to AI agents.

## Status

Milestone 1 (Foundations) — see [docs/MILESTONES.md](docs/MILESTONES.md)
for full progress and [DECISIONS.md](DECISIONS.md) for the design decisions
made so far.

## Local development

Requires Docker and `kubectl`. `kind` and `helm` are expected on `PATH`
(installed as standalone release binaries, not via a package manager).

```bash
make up       # bring up the local kind cluster + backing services
make health   # verify every service is reachable and answering
make status   # kubectl get pods, for a quick look
make down     # tear everything down
```

See [docs/BENCHMARKS.md](docs/BENCHMARKS.md) for measured bring-up times
and [infra/kind/cluster-config.yaml](infra/kind/cluster-config.yaml) for
the full host-port map.
