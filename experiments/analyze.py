"""
Statistical analysis of experiment outputs (results/<tag>/).

Produces in results/<tag>/:
    trial_metrics.csv     one row per (trial, policy)
    summary.csv           mean, sd, 95% CI (Student t) per policy and metric
    paired_tests.csv      Proposed vs every other policy, paired by seed:
                          mean difference, 95% CI of the difference,
                          Wilcoxon signed-rank p-value, Holm-adjusted p
    decision_latency.csv  pooled per-step decision time statistics
    scenario_summary.csv  delivered utility per scenario (mean, CI)
    emergency_*.csv       Emergency window analysis (steps 50-59)
    outcome_breakdown.csv share of each execution outcome per policy
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metrics import episode_metrics  # noqa: E402
from policies import POLICY_ORDER  # noqa: E402

RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")

METRICS = [
    "utility_delivered", "utility_planned", "completion_rate",
    "crit_exec_success", "crit_non_suspension", "crit_deadline_sat",
    "crit_full_rate", "deadline_miss_ratio", "infeasible_rate",
    "infeasible_count", "suspended_steps", "migrations",
    "migration_overhead_ms", "degradations", "fallbacks", "suspensions",
    "energy_total", "energy_onboard", "onboard_cpu_util", "onboard_mem_util",
    "edge_cpu_util", "decision_us_mean", "decision_us_p95",
]
TESTED = ["utility_delivered", "crit_exec_success", "deadline_miss_ratio",
          "completion_rate", "energy_total", "migrations",
          "migration_overhead_ms"]


def ordered(policies):
    return [p for p in POLICY_ORDER if p in policies] + \
        [p for p in policies if p not in POLICY_ORDER]


def ci95(values):
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    n = len(v)
    if n < 2:
        return (float(v.mean()) if n else np.nan), np.nan, np.nan
    m, sd = v.mean(), v.std(ddof=1)
    h = stats.t.ppf(0.975, n - 1) * sd / np.sqrt(n)
    return m, sd, h


def summarise(tm):
    rows = []
    for policy in ordered(tm["policy"].unique()):
        g = tm[tm["policy"] == policy]
        for metric in METRICS:
            m, sd, h = ci95(g[metric])
            rows.append({"policy": policy, "metric": metric, "mean": m,
                         "sd": sd, "ci95": h, "n": int(g[metric].notna().sum())})
    return pd.DataFrame(rows)


def holm(pvals):
    p = np.asarray(pvals, dtype=float)
    order = np.argsort(p)
    adj = np.empty_like(p)
    running = 0.0
    m = len(p)
    for rank, idx in enumerate(order):
        val = min(1.0, (m - rank) * p[idx])
        running = max(running, val)
        adj[idx] = running
    return adj


def paired_tests(tm, reference="Proposed"):
    rows = []
    ref = tm[tm["policy"] == reference].set_index("trial")
    for metric in TESTED:
        block = []
        for policy in ordered(tm["policy"].unique()):
            if policy == reference:
                continue
            other = tm[tm["policy"] == policy].set_index("trial")
            d = (ref[metric] - other[metric]).dropna()
            m, sd, h = ci95(d.values)
            if np.allclose(d.values, 0):
                p = 1.0
            else:
                p = stats.wilcoxon(d.values, zero_method="wilcox").pvalue
            block.append({"metric": metric, "reference": reference,
                          "other": policy, "mean_diff": m, "ci95": h,
                          "wins": int((d > 1e-9).sum()),
                          "ties": int((d.abs() <= 1e-9).sum()),
                          "losses": int((d < -1e-9).sum()), "p_wilcoxon": p})
        adj = holm([b["p_wilcoxon"] for b in block])
        for b, a in zip(block, adj):
            b["p_holm"] = a
        rows.extend(block)
    return pd.DataFrame(rows)


def decision_latency(st):
    rows = []
    for policy in ordered(st["policy"].unique()):
        d = st[st["policy"] == policy]["decision_us"]
        rows.append({"policy": policy, "n": len(d), "mean_us": d.mean(),
                     "min_us": d.min(), "max_us": d.max(),
                     "p95_us": d.quantile(0.95), "median_us": d.median()})
    return pd.DataFrame(rows)


def scenario_summary(wl):
    per = (wl.groupby(["trial", "policy", "scenario"], sort=False)
           ["utility_delivered"].sum().reset_index())
    rows = []
    for (policy, scenario), g in per.groupby(["policy", "scenario"], sort=False):
        m, sd, h = ci95(g["utility_delivered"])
        rows.append({"policy": policy, "scenario": scenario, "mean": m,
                     "sd": sd, "ci95": h})
    return pd.DataFrame(rows)


def emergency(wl):
    em = wl[wl["scenario"] == "Emergency Mission"]
    tm = episode_like(em)
    per_wl = []
    for (policy, workload), g in em.groupby(["policy", "workload"], sort=False):
        per_trial = g.groupby("trial")["utility_delivered"].sum()
        m, sd, h = ci95(per_trial)
        per_wl.append({
            "policy": policy, "workload": workload,
            "utility_mean": m, "utility_ci95": h,
            "share_ok": (g["outcome"] == "ok").mean(),
            "share_full": (g["mode"] == "Full").mean(),
            "share_onboard": (g["location"] == "Onboard").mean(),
            "share_remote": g["location"].isin(
                ["Edge_1", "Edge_2", "AWS_Cloud"]).mean(),
            "share_suspended": (g["outcome"] == "suspended").mean(),
        })
    return tm, pd.DataFrame(per_wl)


def episode_like(sub):
    rows = []
    for (trial, policy), g in sub.groupby(["trial", "policy"], sort=False):
        crit = g[g["critical"]]
        rows.append({"trial": trial, "policy": policy,
                     "utility_delivered": g["utility_delivered"].sum(),
                     "crit_exec_success": (crit["outcome"] == "ok").mean(),
                     "crit_full_rate": ((crit["outcome"] == "ok")
                                        & (crit["mode"] == "Full")).mean(),
                     "completion_rate": (g["outcome"] == "ok").mean(),
                     "migrations": int(g["migrated"].sum())})
    df = pd.DataFrame(rows)
    out = []
    for policy in ordered(df["policy"].unique()):
        g = df[df["policy"] == policy]
        rec = {"policy": policy}
        for metric in ("utility_delivered", "crit_exec_success",
                       "crit_full_rate", "completion_rate", "migrations"):
            m, sd, h = ci95(g[metric])
            rec[metric] = m
            rec[metric + "_ci95"] = h
        out.append(rec)
    return pd.DataFrame(out)


def outcome_breakdown(wl):
    tab = (wl.groupby("policy")["outcome"].value_counts(normalize=True)
           .unstack(fill_value=0.0))
    return tab.loc[ordered(tab.index.tolist())].reset_index()


def analyse(tag):
    d = os.path.join(RESULTS_DIR, tag)
    wl = pd.read_csv(os.path.join(d, "workload_log.csv.gz"))
    st = pd.read_csv(os.path.join(d, "step_log.csv.gz"))
    wl["location"] = wl["location"].fillna("")
    wl["mode"] = wl["mode"].fillna("")
    tm = episode_metrics(wl, st)
    tm.to_csv(os.path.join(d, "trial_metrics.csv"), index=False)
    summarise(tm).to_csv(os.path.join(d, "summary.csv"), index=False)
    if tm["trial"].nunique() > 1 and "Proposed" in set(tm["policy"]):
        paired_tests(tm).to_csv(os.path.join(d, "paired_tests.csv"),
                                index=False)
    decision_latency(st).to_csv(os.path.join(d, "decision_latency.csv"),
                                index=False)
    scenario_summary(wl).to_csv(os.path.join(d, "scenario_summary.csv"),
                                index=False)
    em, em_wl = emergency(wl)
    em.to_csv(os.path.join(d, "emergency_summary.csv"), index=False)
    em_wl.to_csv(os.path.join(d, "emergency_per_workload.csv"), index=False)
    outcome_breakdown(wl).to_csv(os.path.join(d, "outcome_breakdown.csv"),
                                 index=False)
    return tm


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="main")
    a = ap.parse_args()
    analyse(a.tag)
    print(f"analysis written to results/{a.tag}/")
