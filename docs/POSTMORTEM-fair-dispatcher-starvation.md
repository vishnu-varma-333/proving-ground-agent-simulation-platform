# Postmortem: `FairDispatcher` silently starved every run but the first

**Status:** Resolved. **Severity:** High (defeats the scheduler's core
fairness guarantee; would not have been visible without a targeted
test). **Date:** Milestone 6, during local development - caught before
any shared/production deployment existed, so "impact" below describes
what *would* have happened, not an incident that reached real users.

This is the spec's own "a written postmortem" requirement
(Documentation, Production readiness) - a real bug from this project's
own history, written up in the format an actual incident would get,
not a synthetic exercise.

## Summary

`pg_sdk.queue.FairDispatcher` is supposed to cycle fairly across every
run currently in flight, giving a run `priority` consecutive turns per
cycle before moving to the next one - the mechanism that keeps one
large suite from starving others (named directly in the spec's own
design-decision talking points: "Fair scheduling: keeping one large
suite from starving others"). Its `refresh()` method rebuilt that
rotation on every call and *also* unconditionally reset the rotation's
position back to the start - and the worker's main loop calls
`refresh()` before every single `fetch_one()`. The net effect: the
rotation's position never advanced across separate fetch calls. The
alphabetically-first run (Postgres's `ORDER BY r.id`) would be picked
first on every fetch and would dominate for as long as it had anything
pending, while every other concurrently-running suite waited - the
exact starvation this mechanism exists to prevent, produced by code
that otherwise looked like a correct round robin.

## Impact (what would have happened, had this shipped)

Any time two or more suites ran concurrently against the worker fleet,
one of them (whichever sorted first by run id) would complete first
while the others made little or no progress until it finished -
indistinguishable from a priority-starvation bug a user would notice
as "my run is stuck" with no error anywhere, since every individual
simulation would still complete correctly once its turn finally came.
Multi-tenant fairness (the spec's own stated reason for building this
mechanism at all) would have been silently absent from day one.

## Timeline

1. `FairDispatcher` and `refresh()` were implemented and unit-tested
   (equal-weight and priority-weighted cycle construction) during
   Milestone 6's build. Those tests passed - they constructed a cycle
   once and checked its contents and order, never called `refresh()`
   twice in a row the way the real worker loop does.
2. Before running Milestone 6's live fairness test (two runs, equal
   priority, confirming the worker alternates between them), the
   `refresh()` implementation was re-read specifically because the
   worker's main loop calls it before *every* `fetch_one()` - a detail
   that made resetting `_cycle_pos` to 0 unconditionally look suspect
   on inspection, before any test had actually failed.
3. The suspicion was verified two ways, not just asserted: first, a
   regression test was written
   (`test_refresh_does_not_reset_rotation_when_the_active_run_set_is_
   unchanged`, `sdk/pg_sdk/tests/test_queue.py`) and the fix was
   applied, confirming it passed. Then, to make sure the test actually
   exercised the bug rather than passing vacuously, the fix was
   reverted and the same test was re-run - it failed exactly as
   predicted (fetches returning `['msg-from-worker-run-a'] * 4`
   instead of alternating). The fix was then restored and both the
   unit test and Milestone 6's live two-run fairness test passed.

## Root cause

```python
# before
new_cycle = build_weighted_cycle(active_runs)
self._cycle_pos = 0          # <- always reset, every call
self._cycle = new_cycle
```

`refresh()` conflated two different reasons it gets called: (a) the
set of active runs actually changed (a run started or finished - the
cycle's own *contents* need rebuilding, and resetting position is
reasonable), and (b) the worker is just about to fetch again and wants
up-to-date active-run data, which happens on *every* fetch regardless
of whether anything changed. Case (b) is overwhelmingly the common
case in the real loop (`await dispatcher.refresh(active_runs); await
dispatcher.fetch_one()`, every iteration) - and each one silently
rewound progress made by the previous fetch.

## Resolution

```python
# after
if set(new_cycle) != set(self._cycle) or self._cycle_pos >= len(new_cycle):
    self._cycle_pos = 0
self._cycle = new_cycle
```

Only reset position when the cycle's run-id membership actually
changed (or the old position would now be out of bounds against a
shorter cycle) - otherwise keep rotating from wherever the last fetch
left off. `sdk/pg_sdk/src/pg_sdk/queue.py`, `FairDispatcher.refresh()`.

## Why unit tests didn't catch this

Every existing test constructed a `FairDispatcher`, called `refresh()`
*once*, and checked the resulting cycle - which is exactly right for
testing "does this build a correctly weighted cycle," but can't catch
a bug that only manifests across *repeated* calls with an unchanged
active-run set, which is the real worker's actual call pattern. The
regression test added for this fix calls `refresh()` twice with the
same active runs and asserts the second call doesn't reset position -
testing the call pattern, not just the single-call output.

## Lessons / follow-ups

- **A correctness-sensitive piece of state (`_cycle_pos`) that's
  mutated by a method called far more often than the state logically
  needs rebuilding deserves a test that calls that method more than
  once.** Generalizable beyond this one class: anywhere a "refresh"/
  "sync" method is called on every iteration of a hot loop but is only
  supposed to meaningfully change state occasionally, the *repeated-
  call-with-no-real-change* case is exactly where "looks right single-
  call, wrong in practice" bugs like this one hide.
- **Caught by reading the code against its actual caller before
  trusting a test, not by the test failing first.** The live fairness
  test this bug would have broken was about to be run anyway; reading
  `refresh()` against `pg_worker.main`'s loop first is what surfaced
  the suspicion before spending time on a live run that would have
  "passed" for the wrong reason (two runs started and both eventually
  finished - the starvation would only have shown up as both runs
  taking noticeably longer in combination than either would alone,
  easy to miss without a tighter, interleaving-focused assertion).
- **Not yet done:** priority-weighted fairness (a run with
  `priority = 3` getting 3 consecutive turns per cycle) has only been
  exercised by unit tests of `build_weighted_cycle`'s output, not by a
  live run at genuinely unequal priorities - noted as a real, open gap
  in DECISIONS.md and docs/MILESTONES.md rather than implied to be as
  thoroughly proven as the equal-priority case this postmortem covers.
