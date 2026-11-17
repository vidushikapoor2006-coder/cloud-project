"""
Sensitivity analysis of the synthetic modelling assumptions (Reviewer 4).

Each sweep re-runs the seeded trials (same seeds as the main experiment)
while changing ONE assumption; results are written to
results/sensitivity/<sweep>=<value>/ and summarised in
results/sensitivity/sensitivity_summary.csv.

Sweeps:
  noise      stochastic intensity multiplier (0 = deterministic)
  margin     HI-budget headroom delta for critical admission (Proposed,
             AMC-Adapted and Elastic-MC receive the same delta)
  coverage   edge coverage radius [km] (inf = original unlimited model)
  profile    mission-phase profile (flight vs original cruise_only)
  cold_mig   migration downtime counted in the deadline (True/False)
  mig_bw     migration bandwidth B_mig [MB/s]
  horizon    look-ahead horizon H of RH-DP (cost vs benefit)
"""

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from experiments.run_experiments import run, RESULTS_DIR  # noqa: E402
from experiments.analyze import ci95  # noqa: E402
from metrics import episode_metrics  # noqa: E402
from policies import ProposedPolicy, make_policies  # noqa: E402
from baselines.mixed_criticality import MixedCriticalityPolicy  # noqa: E402
from orchestrator.lookahead import LookaheadPolicy  # noqa: E402

CORE = ["Static", "Utility-Based", "AMC-Adapted", "Elastic-MC",
        "Proposed-v1", "Proposed"]
KEY_METRICS = ["utility_delivered", "crit_exec_success", "crit_full_rate",
               "deadline_miss_ratio", "completion_rate", "migrations",
               "decision_us_mean"]


def sweeps(trials):
    yield "noise", [0.0, 0.5, 1.0, 1.5, 2.0], \
        lambda v: dict(noise=v, policies=CORE + ["RH-DP"])
    yield "margin", [0.0, 0.1, 0.2], lambda v: dict(policy_factory=lambda: [
        MixedCriticalityPolicy(elastic=False, margin=v),
        MixedCriticalityPolicy(elastic=True, margin=v),
        ProposedPolicy("revised", margin=v)])
    yield "coverage", [6.0, 8.0, float("inf")], \
        lambda v: dict(coverage=(None if v == float("inf") else v),
                       policies=CORE)
    yield "profile", ["flight", "cruise_only"], \
        lambda v: dict(profile=v, policies=CORE)
    yield "cold_mig", [False, True], lambda v: dict(
        overrides={"MIGRATION_DOWNTIME_IN_DEADLINE": v}, policies=CORE)
    yield "mig_bw", [10.0, 50.0, 100.0], lambda v: dict(
        overrides={"MIGRATION_BANDWIDTH": v}, policies=CORE)
    yield "horizon", [1, 2, 3, 5, 8], lambda v: dict(
        policy_factory=lambda: [LookaheadPolicy(horizon=v)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=config.NUM_TRIALS)
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    out = []
    for name, values, kw in sweeps(a.trials):
        if a.only and name not in a.only.split(","):
            continue
        for v in values:
            tag = os.path.join("sensitivity", f"{name}={v}")
            wl, st = run(a.trials, tag, quiet=True, **kw(v))
            wl["location"] = wl["location"].fillna("")
            wl["mode"] = wl["mode"].fillna("")
            tm = episode_metrics(wl, st)
            for policy, g in tm.groupby("policy"):
                rec = {"sweep": name, "value": str(v), "policy": policy}
                for m in KEY_METRICS:
                    mean, sd, h = ci95(g[m])
                    rec[m] = mean
                    rec[m + "_ci95"] = h
                out.append(rec)
            print(f"sweep {name}={v} done", flush=True)
    df = pd.DataFrame(out)
    path = os.path.join(RESULTS_DIR, "sensitivity", "sensitivity_summary.csv")
    if a.only and os.path.exists(path):
        old = pd.read_csv(path, dtype={"value": str})
        old = old[~old["sweep"].isin(a.only.split(","))]
        df = pd.concat([old, df], ignore_index=True)
    df.to_csv(path, index=False)
    print("written", path)


if __name__ == "__main__":
    main()
