# rapp-ratchet

**Four twins that watch the maintainer, not the machine.**

A ratchet only turns one way. Every check here can be satisfied by doing the work, and none can be satisfied by saying it was done.

---

## The gap it closes

`rapp-sentinel` watches two platforms. [`rapp-overwatch`](https://github.com/kody-w/rapp-overwatch) watches the sentinel. Both watch *programs*.

Nothing watched **the work of maintaining them** — which is done by an agent that writes the fix, writes the test for the fix, and writes the summary saying the fix landed. No part of that loop is adversarial.

It found the gap on its first run:

```
[FAIL] c_sentinel_manifest: required_checks.json not present in the live install
```

A hardening PR had been written, reviewed, tested against its own reproduction, and **left unmerged**. The summary said the sentinel now requires its checks. The running sentinel did not. Both facts were true, and only one of them mattered.

It also surfaced two pull requests sitting 14 and 19 days — real debt that nobody was tracking because filing feels like finishing.

## Four twins

| twin | asks | catches |
|---|---|---|
| **claims** | does the proof still *execute*? | a harness that rotted; a fix merged but not wired |
| **debt** | are findings closed, or just filed? | issues open >7d, PRs open >3d |
| **ratchet** | did coverage go backwards? | a deleted guard, a dropped twin, a shrunken manifest |
| **drift** | does the writing match the measurement? | a README asserting a number the code no longer produces |

## The ratchet property

Counts are stored as a **high-water mark**, never as the last value:

```
guards_proven, overwatch_scenarios, twins_total, sentinel_required
```

A number may rise freely and may never fall. Storing the maximum instead of the latest is what makes *"we quietly deleted a test"* visible a week later instead of never.

## `claims` runs the proof; it does not read it

`c_overwatch_prove` executes `rapp-overwatch/prove.py` and requires every guard to still fire. A proof harness is the first thing to rot, because it is the only file that costs time and produces no feature. Executing it is the only way to know.

That is also why this ticks **hourly** and not every 15 minutes: one tick copies the sentinel two dozen times and takes minutes. The cost is the point — it is the difference between *a proof exists* and *the proof still passes*.

`c_sentinel_manifest` is the same idea applied to a claim: it asserts the manifest exists **and** that `health.py` actually reads it, because a file nobody consults is decoration.

## Every guard here has been seen firing

```
$ python3 prove.py
  [FIRES] c_sentinel_manifest    when: required_checks.json is deleted
  [FIRES] d_prs_landed           when: a pull request has been sitting 20 days
  [FIRES] r_prove_covers_checks  when: a check loses its scenario in prove.py
  ...
  9/9 guards proven to fire and then go quiet
```

This repository enforces *"a guard ships with the reproduction that makes it fire"* on everything else in the stack. It had eight guards and no reproduction for any of them — the only component exempt from its own standard, while catching two real defects in two days.

The two checks that read live GitHub were the reason: they could not be driven to failure on demand. Their data source is now injectable, so `d_findings_closed` and `d_prs_landed` are proven from canned fixtures. Production is untouched — no fixture set means the same `gh` call as before.

`r_prove_covers_checks` closes the loop cheaply: every check must have a scenario, checked on every tick. Running the whole harness hourly would cost minutes to re-prove scenarios that only change when `checks.py` changes. What rots silently is **coverage** — a new guard quietly joining the set nobody has watched fail.

It found its own gap immediately: added to `BY_TWIN`, it failed on itself for having no scenario.

## Run it

```bash
python3 prove.py             # make all 9 guards fire
python3 ratchet.py verdict   # run the checks, print, change nothing
python3 ratchet.py tick      # + emit four frames and anchor
python3 ratchet.py report    # the paragraph a person needs
python3 twins.py roll-call   # our four chains

bash install-launchd.sh      # hourly, via launchd
```

Independent by construction: its own identities, chains, anchors, and launchd job, sharing only the `rapp/1` frame format (vendored, authority [`kody-w/rapp-1`](https://github.com/kody-w/rapp-1)).

## What it deliberately does not do

No repair arm, no escalation, no writes to either subject. It reports, and a person decides. Three autonomous things repairing one estate is worse than two, and two is already a fix racing its own revert at 3am.

It also cannot check its own checks — nothing can. That regress is infinite and the honest stopping point is stating where it ends: **this file is the last one, and a human reads it.**

MIT © RAPP ecosystem — see the [map](https://github.com/kody-w/rapp-map).
