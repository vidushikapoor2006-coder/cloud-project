from dataclasses import dataclass
from models.workload import Criticality


@dataclass
class ScenarioMetrics:

    scenario: str

    total_utility: float = 0.0

    workloads_completed: int = 0
    workloads_infeasible: int = 0

    critical_workloads_successful: int = 0
    critical_workloads_total: int = 0

    adaptations: int = 0
    migrations: int = 0
    degradations: int = 0
    fallbacks: int = 0
    suspensions: int = 0


def calculate_scenario_metrics(
    scenario_name,
    decisions,
    system
):

    metrics = ScenarioMetrics(
        scenario=scenario_name
    )

    for decision in decisions:

        # No feasible allocation
        if decision["location"] is None:

            metrics.workloads_infeasible += 1

            workload = next(
                w for w in system.workloads
                if w.name == decision["workload"]
            )

            if workload.criticality == Criticality.VERY_HIGH:
                metrics.critical_workloads_total += 1

            continue

        # Workload successfully allocated
        metrics.workloads_completed += 1

        workload = next(
            w for w in system.workloads
            if w.name == decision["workload"]
        )

        # Mission utility
        metrics.total_utility += decision["details"]["utility"]

        # Critical workload tracking
        if workload.criticality == Criticality.VERY_HIGH:

            metrics.critical_workloads_total += 1

            metrics.critical_workloads_successful += 1

        # Adaptation
        if decision["adapted"]:

            metrics.adaptations += 1

            adaptation_type = decision.get(
                "adaptation_type",
                ""
            )

            if "Migration" in adaptation_type:
                metrics.migrations += 1

            if "Degradation" in adaptation_type:
                metrics.degradations += 1

            if "Fallback" in adaptation_type:
                metrics.fallbacks += 1

            if "Suspension" in adaptation_type:
                metrics.suspensions += 1

    return metrics

# =====================================================================
# Revised metrics (this revision).  Computed from the per-workload execution
# log written by simulation/engine.py.  See Section VI-D of the paper.
# =====================================================================

EXECUTED_MODES = ("Full", "Reduced", "Fallback")


def episode_metrics(wl, st):
    """Per-(trial, policy) metrics from workload rows ``wl`` and step rows ``st``.

    Definitions
    -----------
    utility_delivered     sum of U_i over workload-steps whose outcome is 'ok'
    utility_planned       sum of U_i over all non-suspended assignments
    completion_rate       #ok / #workload-steps
    crit_exec_success     #ok / #critical workload-steps
    crit_non_suspension   #critical workload-steps with an executable
                          (Full/Reduced/Fallback) assignment / #critical
                          (this is what the original paper called
                          "critical preservation")
    crit_deadline_sat     #critical ok / #critical that actually executed
                          (outcome ok or deadline)  -- "where applicable"
    crit_full_rate        #critical ok in Full mode / #critical
    deadline_miss_ratio   #attempted that did not complete within the
                          deadline (deadline, resource, link, host) /
                          #attempted, attempted = executable assignment
    infeasible_rate       #no-feasible-action / #workload-steps
    """
    import numpy as np
    import pandas as pd

    rows = []
    for (trial, policy), g in wl.groupby(["trial", "policy"], sort=False):
        crit = g[g["critical"]]
        executed_crit = crit[crit["outcome"].isin(["ok", "deadline"])]
        attempted = g[g["mode"].isin(EXECUTED_MODES)]
        s = st[(st["trial"] == trial) & (st["policy"] == policy)]
        adapt = g["adaptation"].fillna("")
        rows.append({
            "trial": trial, "policy": policy,
            "utility_delivered": g["utility_delivered"].sum(),
            "utility_planned": g["utility_planned"].sum(),
            "completion_rate": (g["outcome"] == "ok").mean(),
            "crit_exec_success": (crit["outcome"] == "ok").mean(),
            "crit_non_suspension": crit["mode"].isin(EXECUTED_MODES).mean(),
            "crit_deadline_sat": ((executed_crit["outcome"] == "ok").mean()
                                  if len(executed_crit) else np.nan),
            "crit_full_rate": ((crit["outcome"] == "ok")
                               & (crit["mode"] == "Full")).mean(),
            "deadline_miss_ratio": ((attempted["outcome"] != "ok").mean()
                                    if len(attempted) else np.nan),
            "infeasible_rate": (g["outcome"] == "infeasible").mean(),
            "infeasible_count": int((g["outcome"] == "infeasible").sum()),
            "suspended_steps": int((g["outcome"] == "suspended").sum()),
            "migrations": int(g["migrated"].sum()),
            "migration_overhead_ms": g.loc[g["migrated"], "migration_ms"].sum(),
            "degradations": int(adapt.str.contains("Degradation").sum()),
            "fallbacks": int(adapt.str.contains("Fallback").sum()),
            "suspensions": int(adapt.str.contains("Suspension").sum()),
            "energy_total": g["energy"].sum(),
            "energy_onboard": g.loc[g["location"] == "Onboard", "energy"].sum(),
            "onboard_cpu_util": s["onboard_cpu_util"].mean(),
            "onboard_mem_util": s["onboard_mem_util"].mean(),
            "edge_cpu_util": s["edge_cpu_util"].mean(),
            "decision_us_mean": s["decision_us"].mean(),
            "decision_us_p95": s["decision_us"].quantile(0.95),
        })
    return pd.DataFrame(rows)
