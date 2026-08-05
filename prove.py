#!/usr/bin/env python3
"""prove.py — make every ratchet guard fire on purpose, then confirm it stops.

    python3 prove.py

This repository enforces one rule on everything else in the stack: a guard
ships with the reproduction that makes it fire. It had eight guards and no
reproduction for any of them, which made it the only component exempt from its
own standard — and that standard exists because a guard nobody has watched fail
is indistinguishable from a guard that cannot fail.

Each scenario slips a THROWAWAY COPY and asserts the matching check fails, then
asserts it passes on a clean copy. Both halves matter: a check that fails on
everything is as useless as one that fails on nothing, and only the pair tells
them apart.

Neither ~/rapp-overwatch nor ~/rapp-sentinel is ever modified. Every scenario
copies first, and the two checks that read live GitHub are driven from canned
fixtures rather than the network.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path(__file__).resolve().parent
REAL_OVERWATCH = Path(os.path.expanduser("~/rapp-overwatch"))
REAL_SENTINEL = Path(os.path.expanduser("~/rapp-sentinel"))

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"
IGNORE = shutil.ignore_patterns("__pycache__", ".git", "logs", "node_modules")

# Built at runtime so this literal never appears twice in the file. An earlier
# draft hardcoded it, and a later edit matched the copy inside a helper instead
# of the list itself, corrupting the harness.
LIST_MARKER = "SCENARIOS" + " = ["


def run_check(name, env_extra):
    """Run ONE check in a subprocess with its own environment, so scenarios
    cannot contaminate each other through shared state or a cached module."""
    env = dict(os.environ, **{k: str(v) for k, v in env_extra.items()})
    code = f"import json,checks; print(json.dumps(checks.{name}()))"
    r = subprocess.run([sys.executable, "-c", code], cwd=HOME, env=env,
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        return {"id": name, "ok": None, "detail": f"harness error: {r.stderr.strip()[-300:]}"}
    return json.loads(r.stdout.strip().splitlines()[-1])


def _write(p: Path, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _truncate_scenarios(path: Path, keep):
    """Drop all but the first `keep` scenario lines from a prove.py."""
    body = path.read_text(encoding="utf-8")
    head, _, tail = body.partition(LIST_MARKER)
    listing, _, rest = tail.partition("\n]")
    kept = "\n".join(listing.splitlines()[:keep])
    path.write_text(head + LIST_MARKER + kept + "\n]" + rest, encoding="utf-8")


def _stub_prove(path: Path, fired, total):
    """A prove.py that reports a verdict without running the real harness.

    The check under test is whether c_overwatch_prove RUNS a harness and reads
    its verdict — not whether the overwatch's 13 guards work, which that
    repository's own prove.py already covers. Stubbing keeps this scenario at
    seconds instead of minutes and tests the right thing.
    """
    _write(path, "print('  %d/%d guards proven to fire and then go quiet')\n" % (fired, total))


def sandbox(tmp, tag, *, overwatch=True, sentinel=False, ratchet=False):
    base = Path(tmp) / tag
    env = {"RATCHET_STATE": str(base / "state")}
    (base / "state").mkdir(parents=True, exist_ok=True)
    if overwatch:
        shutil.copytree(REAL_OVERWATCH, base / "overwatch", ignore=IGNORE)
        env["RATCHET_OVERWATCH"] = str(base / "overwatch")
    if sentinel:
        shutil.copytree(REAL_SENTINEL, base / "sentinel", ignore=IGNORE)
        env["RATCHET_SENTINEL"] = str(base / "sentinel")
    if ratchet:
        shutil.copytree(HOME, base / "ratchet", ignore=IGNORE)
        env["RATCHET_SELF"] = str(base / "ratchet")
    return base, env


# ── scenarios ───────────────────────────────────────────────────────────────

def sc_prove(tmp, tag, slip):
    base, env = sandbox(tmp, tag)
    _stub_prove(Path(env["RATCHET_OVERWATCH"]) / "prove.py", 4 if slip else 13, 13)
    return env


def sc_manifest(tmp, tag, slip):
    base, env = sandbox(tmp, tag, overwatch=False, sentinel=True)
    if slip:
        (Path(env["RATCHET_SENTINEL"]) / "required_checks.json").unlink()
    return env


def sc_findings(tmp, tag, slip):
    base, env = sandbox(tmp, tag, overwatch=False)
    fx = base / "gh"
    fx.mkdir(parents=True, exist_ok=True)
    _write(fx / "issue-list-kody-w_rapp-sentinel-open-50-number_title_createdAt.json",
           json.dumps([{"number": 1, "title": "an unattended finding",
                        "createdAt": _iso(40 if slip else 1)}]))
    env["RATCHET_GH_FIXTURE"] = str(fx)
    return env


def sc_prs(tmp, tag, slip):
    base, env = sandbox(tmp, tag, overwatch=False)
    fx = base / "gh"
    fx.mkdir(parents=True, exist_ok=True)
    for repo in ("kody-w_rapp-sentinel", "kody-w_openrappter"):
        _write(fx / f"pr-list-{repo}-open-30-number_createdAt_title.json",
               json.dumps([{"number": 9, "createdAt": _iso(20 if slip else 0),
                            "title": "a PR left sitting"}]))
    env["RATCHET_GH_FIXTURE"] = str(fx)
    return env


def sc_guards(tmp, tag, slip):
    base, env = sandbox(tmp, tag)
    _write(Path(env["RATCHET_STATE"]) / "highwater.json",
           json.dumps({"overwatch_scenarios": 13}))
    if slip:
        _truncate_scenarios(Path(env["RATCHET_OVERWATCH"]) / "prove.py", 4)
    return env


def sc_twins(tmp, tag, slip):
    base, env = sandbox(tmp, tag, ratchet=True)
    _write(Path(env["RATCHET_STATE"]) / "highwater.json", json.dumps({"twins_total": 7}))
    if slip:
        tp = Path(env["RATCHET_SELF"]) / "twins.py"
        tp.write_text(tp.read_text(encoding="utf-8").replace(
            '    "drift":   "checks that the documentation still matches the measured code",\n',
            "", 1), encoding="utf-8")
    return env


def sc_readme(tmp, tag, slip):
    base, env = sandbox(tmp, tag)
    if slip:
        rp = Path(env["RATCHET_OVERWATCH"]) / "README.md"
        rp.write_text(rp.read_text(encoding="utf-8").replace("13/13 guards", "99/99 guards"),
                      encoding="utf-8")
    return env


def sc_reachable(tmp, tag, slip):
    base, env = sandbox(tmp, tag, overwatch=not slip)
    if slip:
        env["RATCHET_OVERWATCH"] = str(base / "definitely-not-here")
    return env


def sc_prove_coverage(tmp, tag, slip):
    """A check with no scenario is a guard nobody has watched fail."""
    base, env = sandbox(tmp, tag, overwatch=False, ratchet=True)
    if slip:
        _truncate_scenarios(Path(env["RATCHET_SELF"]) / "prove.py", 3)
    return env


SCENARIOS = [
    ("c_overwatch_prove",     "the guard harness reports 4 of 13 firing",        sc_prove),
    ("c_sentinel_manifest",   "required_checks.json is deleted",                 sc_manifest),
    ("d_findings_closed",     "a finding has been open 40 days",                 sc_findings),
    ("d_prs_landed",          "a pull request has been sitting 20 days",         sc_prs),
    ("r_overwatch_guards",    "guard scenarios drop below the high-water mark",  sc_guards),
    ("r_twin_count",          "a twin is deleted",                               sc_twins),
    ("r_prove_covers_checks", "a check loses its scenario in prove.py",          sc_prove_coverage),
    ("f_readme_matches_code", "the README claims a guard count the code denies", sc_readme),
    ("f_subject_reachable",   "a watched subject directory is gone",             sc_reachable),
]


def main():
    for p, n in ((REAL_OVERWATCH, "rapp-overwatch"), (REAL_SENTINEL, "rapp-sentinel")):
        if not p.is_dir():
            print(f"{n} not found at {p}")
            return 2

    print(f"prove.py — every ratchet guard must be seen firing\n{'=' * 74}")
    passed = failed = 0
    with tempfile.TemporaryDirectory(prefix="ratchet-prove-") as tmp:
        for i, (name, desc, build) in enumerate(SCENARIOS):
            clean = run_check(name, build(tmp, f"{i:02d}-{name}-clean", False))
            slipped = run_check(name, build(tmp, f"{i:02d}-{name}-slip", True))

            good = clean.get("ok") is True and slipped.get("ok") is False
            passed, failed = (passed + 1, failed) if good else (passed, failed + 1)
            print(f"  [{GREEN + 'FIRES' + RESET if good else RED + 'BROKEN' + RESET}] {name}")
            print(f"{DIM}          when: {desc}{RESET}")
            if good:
                print(f"{DIM}          said: {slipped['detail'][:96]}{RESET}")
            else:
                print(f"          clean -> ok={clean.get('ok')} {clean.get('detail','')[:70]}")
                print(f"          slip  -> ok={slipped.get('ok')} {slipped.get('detail','')[:70]}")

    print("=" * 74)
    print(f"  {passed}/{len(SCENARIOS)} guards proven to fire and then go quiet")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
