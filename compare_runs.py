"""
compare_runs.py  -- catch regressions between two test runs.
============================================================

Pretty Good AI's own "95-5" thesis: most healthcare AI fails because it doesn't
improve over time and silently breaks as you ship. This is the safety net for that:
run the test battery, then diff this run's scorecard against a frozen baseline. If a
new version BROKE something the last version handled, this flags it (and exits non-zero
so it can fail a release check).

Usage:
    python compare_runs.py                         # baseline.json vs scorecard.json
    python compare_runs.py baseline.json new.json  # explicit files

Exit code 0 = no regressions, 1 = regressions found (so CI can gate on it).
"""

import sys
import json
import pathlib

HERE = pathlib.Path(__file__).parent


def load(path):
    return json.loads(pathlib.Path(path).read_text())


def main():
    base_path = sys.argv[1] if len(sys.argv) > 1 else HERE / "baseline.json"
    new_path = sys.argv[2] if len(sys.argv) > 2 else HERE / "scorecard.json"
    base, new = load(base_path), load(new_path)

    regressions, improvements = [], []

    for scenario in sorted(set(base) & set(new)):
        b, n = base[scenario], new[scenario]

        # Safety going from OK -> not OK is the worst kind of regression.
        if b.get("safety_ok") is True and n.get("safety_ok") is False:
            regressions.append(f"CRITICAL  {scenario}: safety broke (safe -> UNSAFE)")
        elif b.get("safety_ok") is False and n.get("safety_ok") is True:
            improvements.append(f"{scenario}: safety fixed")

        # Containment going true -> false.
        if b.get("contained") and not n.get("contained"):
            regressions.append(f"REGRESSION {scenario}: no longer contained (was contained)")
        elif not b.get("contained") and n.get("contained"):
            improvements.append(f"{scenario}: now contained")

        # A meaningful quality drop.
        bq, nq = b.get("quality") or 0, n.get("quality") or 0
        if bq - nq >= 2:
            regressions.append(f"REGRESSION {scenario}: quality dropped {bq} -> {nq}")

    print(f"Compared {len(set(base) & set(new))} scenarios: "
          f"{base_path.name if hasattr(base_path,'name') else base_path} (baseline) "
          f"vs {new_path.name if hasattr(new_path,'name') else new_path}\n")

    if improvements:
        print("Improvements:")
        for i in improvements:
            print("  +", i)
        print()

    if regressions:
        print("REGRESSIONS:")
        for r in regressions:
            print("  -", r)
        print("\nResult: FAIL (regressions found) -- do not ship this version.")
        sys.exit(1)

    print("Result: PASS -- no regressions vs baseline.")
    sys.exit(0)


if __name__ == "__main__":
    main()
