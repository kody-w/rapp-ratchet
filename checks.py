#!/usr/bin/env python3
"""checks.py — what "the maintainer got lazy" looks like, in files.

The subject here is not a program. It is the work of keeping the other two
watchers honest, which is done by an agent that has every incentive to declare
victory: it writes the fix, writes the test for the fix, and writes the summary
saying the fix landed. Nothing in that loop is adversarial.

So these checks are deliberately the ones an author would not run on themselves:

  claims   the proof still executes, not "was written once"
  debt     findings get closed, not just filed
  ratchet  coverage may increase and may not decrease
  drift    the documentation still matches the measurement

A ratchet only turns one way. That is the whole idea: any of these can be
satisfied by doing the work, and none can be satisfied by saying it was done.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

CRITICAL, WARN = "critical", "warn"
HOME = Path(__file__).resolve().parent
STATE = Path(os.environ.get("RATCHET_STATE", str(HOME / "state")))
HIGHWATER = STATE / "highwater.json"

OVERWATCH = Path(os.path.expanduser(os.environ.get("RATCHET_OVERWATCH", "~/rapp-overwatch")))
SENTINEL = Path(os.path.expanduser(os.environ.get("RATCHET_SENTINEL", "~/rapp-sentinel")))


def ok(cid, detail):
    return {"id": cid, "ok": True, "severity": WARN, "detail": detail}


def fail(cid, detail, critical=False):
    return {"id": cid, "ok": False, "severity": CRITICAL if critical else WARN,
            "detail": detail}


def _self_dir() -> Path:
    """Our own tree, overridable so guards ABOUT this repo can be proven.

    A guard that can only ever read the live checkout cannot be driven to
    failure, which is the exact property this repository refuses to accept
    anywhere else.
    """
    return Path(os.path.expanduser(os.environ.get("RATCHET_SELF", str(HOME))))


def _highwater(key, value):
    """Record the best ever seen. Returns (best, regressed_by).

    The ratchet: a number may go up freely and may never come down. Storing the
    maximum rather than the last value is what makes 'we quietly deleted a test'
    visible a week later instead of never.
    """
    STATE.mkdir(parents=True, exist_ok=True)
    hw = {}
    if HIGHWATER.exists():
        try:
            hw = json.loads(HIGHWATER.read_text(encoding="utf-8"))
        except Exception:
            hw = {}
    best = max(int(hw.get(key, 0)), int(value))
    if best != hw.get(key):
        hw[key] = best
        HIGHWATER.write_text(json.dumps(hw, indent=2) + "\n", encoding="utf-8")
    return best, max(0, best - int(value))


def _gh(args, timeout=90):
    """Run gh, or read a canned response when a fixture directory is set.

    The two debt checks read live GitHub state, which made them the only guards
    here that could not be driven to failure on demand. By this repository's own
    standard that is indistinguishable from a guard that cannot fail, so the
    data source is injectable.

    Production is untouched: with RATCHET_GH_FIXTURE unset this is the same
    subprocess call it always was.
    """
    fixture_dir = os.environ.get("RATCHET_GH_FIXTURE")
    if fixture_dir:
        key = "-".join(a for a in args if not a.startswith("--"))
        key = re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json"
        path = Path(fixture_dir) / key
        if not path.is_file():
            raise RuntimeError(f"no gh fixture for {key}")
        return path.read_text(encoding="utf-8")
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "gh failed").strip()[:200])
    return r.stdout


# ── claims: does the proof still run? ────────────────────────────────────────

def c_overwatch_prove():
    """Run the guard proof. Not 'does prove.py exist' — does it still pass.

    A proof harness is the first thing to rot, because it is the only file that
    costs time and produces no feature. Executing it is the only way to know.
    """
    p = OVERWATCH / "prove.py"
    if not p.exists():
        return fail("c_overwatch_prove", "rapp-overwatch/prove.py is gone", critical=True)
    try:
        r = subprocess.run(["python3", "prove.py"], cwd=str(OVERWATCH),
                           capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return fail("c_overwatch_prove", "prove.py did not finish in 900s", critical=True)
    m = re.search(r"(\d+)/(\d+) guards proven", r.stdout or "")
    if not m:
        return fail("c_overwatch_prove",
                    f"prove.py produced no verdict (rc={r.returncode})", critical=True)
    fired, total = int(m.group(1)), int(m.group(2))
    best, regressed = _highwater("guards_proven", fired)
    if fired < total:
        return fail("c_overwatch_prove",
                    f"only {fired}/{total} guards fire", critical=True)
    if regressed:
        return fail("c_overwatch_prove",
                    f"{fired} guards proven, down {regressed} from {best}", critical=True)
    return ok("c_overwatch_prove", f"{fired}/{total} guards still fire")


def c_sentinel_manifest():
    """The require-don't-enumerate fix: verify it is actually wired, not merged.

    A merged PR is not a working guard. This asserts the manifest exists AND
    that health.py consults it, because a file nobody reads is decoration.
    """
    man = SENTINEL / "required_checks.json"
    health = SENTINEL / "health.py"
    if not man.exists():
        return fail("c_sentinel_manifest", "required_checks.json not present in the live install")
    if not health.exists():
        return fail("c_sentinel_manifest", "health.py missing", critical=True)
    if "required_checks.json" not in health.read_text(encoding="utf-8"):
        return fail("c_sentinel_manifest",
                    "manifest exists but health.py never reads it", critical=True)
    try:
        n = len(json.loads(man.read_text(encoding="utf-8"))["required"])
    except Exception as e:
        return fail("c_sentinel_manifest", f"manifest unreadable: {e}", critical=True)
    best, regressed = _highwater("sentinel_required", n)
    if regressed:
        return fail("c_sentinel_manifest",
                    f"{n} required checks, down {regressed} from {best}", critical=True)
    return ok("c_sentinel_manifest", f"manifest wired into health.py, {n} required checks")


# ── debt: are findings closed, or just filed? ────────────────────────────────

def _age_days(ts):
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds() / 86400
    except Exception:
        return None


def d_findings_closed():
    """Filing an issue feels like progress and closes nothing.

    Reported, never critical: an open issue is a decision to do it later, and
    later is legitimate. What is not legitimate is losing track, so the count
    and the age are always in front of you.
    """
    try:
        raw = _gh(["issue", "list", "--repo", "kody-w/rapp-sentinel",
                   "--state", "open", "--limit", "50",
                   "--json", "number,title,createdAt"])
    except Exception as e:
        return fail("d_findings_closed", f"could not list issues: {e}")
    items = json.loads(raw or "[]")
    aged = [(i["number"], _age_days(i["createdAt"]) or 0, i["title"]) for i in items]
    stale = [a for a in aged if a[1] > 7]
    if stale:
        worst = max(stale, key=lambda a: a[1])
        return fail("d_findings_closed",
                    f"{len(stale)} finding(s) open >7d; oldest #{worst[0]} "
                    f"{worst[1]:.0f}d: {worst[2][:50]}")
    return ok("d_findings_closed", f"{len(items)} open, none older than 7d")


def d_prs_landed():
    """An open PR is work that has not shipped, however good the diff is."""
    out = []
    for repo in ("kody-w/rapp-sentinel", "kody-w/openrappter"):
        try:
            raw = _gh(["pr", "list", "--repo", repo, "--state", "open",
                       "--limit", "30", "--json", "number,createdAt,title"])
        except Exception as e:
            return fail("d_prs_landed", f"could not list PRs for {repo}: {e}")
        for pr in json.loads(raw or "[]"):
            age = _age_days(pr["createdAt"]) or 0
            if age > 3:
                out.append(f"{repo.split('/')[-1]}#{pr['number']} {age:.0f}d")
    if out:
        return fail("d_prs_landed", f"{len(out)} PR(s) open >3d: " + ", ".join(out[:6]))
    return ok("d_prs_landed", "no pull request has been sitting more than 3d")


# ── ratchet: coverage only goes up ───────────────────────────────────────────

def r_overwatch_guards():
    """Count the guards the proof harness declares, independent of running it."""
    p = OVERWATCH / "prove.py"
    if not p.exists():
        return fail("r_overwatch_guards", "prove.py is gone", critical=True)
    body = p.read_text(encoding="utf-8")
    block = re.search(r"SCENARIOS\s*=\s*\[(.*?)\n\]", body, re.S)
    n = len(re.findall(r'\(\s*"', block.group(1))) if block else 0
    best, regressed = _highwater("overwatch_scenarios", n)
    if regressed:
        return fail("r_overwatch_guards",
                    f"{n} scenarios, down {regressed} from {best}", critical=True)
    return ok("r_overwatch_guards", f"{n} guard scenarios (high-water {best})")


def r_twin_count():
    """Twins may be added. A twin that disappears takes a vantage with it."""
    # SELF is overridable so this guard can be driven to failure against a
    # throwaway copy. It counts our own twins as well as the overwatch's, and a
    # guard that can only ever read the live tree cannot be proven.
    self_dir = _self_dir()
    total = 0
    for repo in (OVERWATCH, self_dir):
        tp = repo / "twins.py"
        if not tp.exists():
            return fail("r_twin_count", f"{repo.name}/twins.py missing", critical=True)
        blk = re.search(r"TWINS\s*=\s*\{(.*?)\n\}", tp.read_text(encoding="utf-8"), re.S)
        total += len(re.findall(r'^\s*"', blk.group(1), re.M)) if blk else 0
    best, regressed = _highwater("twins_total", total)
    if regressed:
        return fail("r_twin_count", f"{total} twins, down {regressed} from {best}",
                    critical=True)
    return ok("r_twin_count", f"{total} twins across both neighborhoods")


# ── drift: does the writing still match the measurement? ─────────────────────

def f_readme_matches_code():
    """A README asserting a number is a claim, and claims decay silently.

    rapp-overwatch's README says N/N guards fire. If prove.py grows a scenario
    and the prose does not, the document is quietly wrong — and the document is
    what a stranger reads to decide whether any of this is trustworthy.
    """
    rp = OVERWATCH / "README.md"
    pp = OVERWATCH / "prove.py"
    if not rp.exists() or not pp.exists():
        return fail("f_readme_matches_code", "overwatch README or prove.py missing")
    blk = re.search(r"SCENARIOS\s*=\s*\[(.*?)\n\]", pp.read_text(encoding="utf-8"), re.S)
    actual = len(re.findall(r'\(\s*"', blk.group(1))) if blk else 0
    claims = {int(m) for m in re.findall(r"(\d+)\s*/\s*\d+\s+guards", rp.read_text(encoding="utf-8"))}
    if not claims:
        return ok("f_readme_matches_code", "README makes no guard-count claim")
    wrong = sorted(c for c in claims if c != actual)
    if wrong:
        return fail("f_readme_matches_code",
                    f"README claims {wrong} guards; prove.py defines {actual}")
    return ok("f_readme_matches_code", f"README's {actual}-guard claim matches prove.py")


def f_subject_reachable():
    """Both subjects still exist where the config says they do.

    Trivial until the day a directory is renamed and three watchers start
    reporting a clean bill of health about nothing at all.
    """
    missing = [str(p) for p in (OVERWATCH, SENTINEL) if not p.is_dir()]
    if missing:
        return fail("f_subject_reachable", "not found: " + ", ".join(missing), critical=True)
    return ok("f_subject_reachable", "overwatch and sentinel both present")


def r_prove_covers_checks():
    """Every check here must have a scenario in prove.py.

    This repository enforces "a guard ships with the reproduction that makes it
    fire" on everything else, and had eight guards and no reproduction for any
    of them. Adding a check without a scenario is the regression that matters,
    and it is silent -- the new guard simply joins the set nobody has watched
    fail.

    Deliberately cheap. Running the whole harness on every tick would cost
    minutes and only re-prove scenarios that change when this file changes;
    c_overwatch_prove already pays that price one level down, and CI can pay it
    here. What is checked on every tick is COVERAGE, because that is what
    silently rots.
    """
    pp = _self_dir() / "prove.py"
    if not pp.is_file():
        return fail("r_prove_covers_checks", "prove.py is gone", critical=True)
    body = pp.read_text(encoding="utf-8")
    block = re.search(r"SCENARIOS\s*=\s*\[(.*?)\n\]", body, re.S)
    covered = set(re.findall(r'\(\s*"([a-z0-9_]+)"', block.group(1))) if block else set()
    declared = {fn.__name__ for fns in BY_TWIN.values() for fn in fns}
    missing = sorted(declared - covered)
    if missing:
        return fail("r_prove_covers_checks",
                    f"{len(missing)} check(s) have no scenario: " + ", ".join(missing),
                    critical=True)
    best, regressed = _highwater("prove_scenarios", len(covered))
    if regressed:
        return fail("r_prove_covers_checks",
                    f"{len(covered)} scenarios, down {regressed} from {best}", critical=True)
    return ok("r_prove_covers_checks",
              f"all {len(declared)} checks have a scenario ({len(covered)} total)")


BY_TWIN = {
    "claims":  [c_overwatch_prove, c_sentinel_manifest],
    "debt":    [d_findings_closed, d_prs_landed],
    "ratchet": [r_overwatch_guards, r_twin_count, r_prove_covers_checks],
    "drift":   [f_readme_matches_code, f_subject_reachable],
}


def all_checks():
    for fns in BY_TWIN.values():
        yield from fns
