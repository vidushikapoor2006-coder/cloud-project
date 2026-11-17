"""
Experiment engine: runs one policy on one environment trace and records
per-workload decisions and execution outcomes (Reviewer 2 comments 4, 8;
Reviewer 4).

Separation of concerns
----------------------
* decision time      -- wall-clock time of policy.decide() ONLY
                        (time.perf_counter_ns), excluding simulation,
                        logging and any AWS communication;
* simulation time    -- time of the execution model and bookkeeping;
* AWS communication  -- not part of this engine (see main.py --aws).

Execution model (realised outcome of a decision)
------------------------------------------------
For every step the policy decides on the OBSERVED state.  The selected
actions are then executed against the REALISED state of the same step
(intra-step latency jitter, demand deviation, background-load deviation and
possible link drop, all pre-generated in the trace).  On every host the
admitted jobs are served in decreasing criticality (then phase importance),
i.e. a criticality-priority host scheduler identical for all policies.

A workload-step has exactly one outcome:
    ok          executed and response time <= deadline (SUCCESS)
    deadline    executed but realised response time > deadline
    resource    not admitted: realised CPU/memory/energy insufficient
    link        remote location unreachable during the step
    host        host unavailable (e.g. cloud failure)
    suspended   intentionally suspended by the policy
    infeasible  no feasible action was found by the policy
"""

import time

import config
from models.catalog import create_system
from models.workload import Criticality, ExecutionMode, Location
from orchestrator.feasibility import (
    network_latency, get_resource_for_location, link_is_up,
)
from orchestrator.history import classify_adaptation
from orchestrator.migration import raw_migration_time_ms
from orchestrator.utility import calculate_utility, MISSION_IMPORTANCE, QUALITY_FACTOR
from simulation.environment import apply_observation

HOST_OF = {
    Location.ONBOARD: "Onboard",
    Location.EDGE_1: "Edge_1",
    Location.EDGE_2: "Edge_2",
    Location.CLOUD: "AWS_Cloud",
}


def _in_coverage(location, system):
    if location not in (Location.EDGE_1, Location.EDGE_2):
        return True
    radius = (float("inf") if system.coverage_radius_km is None
              else system.coverage_radius_km)
    return config.edge_in_coverage(location.value, system.evtol_position,
                                   radius_km=radius)


def _realised_migration_ms(workload, old, new, system, latency_factor):
    planned = raw_migration_time_ms(workload, old, new, system)
    if planned == 0.0:
        return 0.0
    if old.value.startswith("Edge_") and new.value.startswith("Edge_"):
        return planned
    return planned + float(system.network.latency) * (latency_factor - 1.0)


def run_episode(policy, trace, trial=0, coverage_radius_km="default",
                record_rows=True):
    coverage = (config.EDGE_COVERAGE_RADIUS_KM
                if coverage_radius_km == "default" else coverage_radius_km)
    system = create_system(coverage_radius_km=coverage)
    if hasattr(policy, "reset"):
        policy.reset()

    rows = []
    steps = []
    by_name = {w.name: w for w in system.workloads}

    for step in trace:
        apply_observation(system, step)
        snapshot = {
            w.name: (w.current_location, w.current_mode, w.previous_location)
            for w in system.workloads
        }
        ctx = {"t": step.t, "trace": trace}

        t0 = time.perf_counter_ns()
        decisions = policy.decide(system, ctx)
        decision_ns = time.perf_counter_ns() - t0

        t1 = time.perf_counter_ns()
        decision_map = {d["workload"]: d for d in decisions}
        phase = system.mission.phase

        # ---------------- execution against the realised state -----------
        used = {h: {"cpu": 0.0, "mem": 0.0, "energy": 0.0}
                for h in config.HOST_CAPACITY}
        avail = {}
        for loc, host in HOST_OF.items():
            res = get_resource_for_location(loc, system)
            cap_cpu, cap_mem = config.HOST_CAPACITY[host]
            bg = min(max(res.cpu_used + step.real_bg_delta.get(host, 0.0), 0.0),
                     cap_cpu)
            avail[host] = {
                "cpu": cap_cpu - bg, "bg_cpu": bg,
                "mem": cap_mem - res.memory_used,
                "energy": res.energy_available,
                "up": res.available,
            }

        order = sorted(
            system.workloads,
            key=lambda w: (w.criticality.value,
                           MISSION_IMPORTANCE[w.name][phase]),
            reverse=True,
        )
        outcome_rows = {}
        for w in order:
            d = decision_map.get(w.name, {"location": None, "mode": None})
            loc, mode = d.get("location"), d.get("mode")
            prev_loc, prev_mode, prev_prev = snapshot[w.name]
            row = {
                "trial": trial, "policy": policy.name, "t": step.t,
                "scenario": step.scenario, "phase": phase.name,
                "workload": w.name,
                "critical": w.criticality == Criticality.VERY_HIGH,
                "location": loc.value if loc is not None else "",
                "mode": mode.value if mode is not None else "",
                "deadline_ms": w.deadline,
                "planned_feasible": d.get("planned_feasible", loc is not None),
                "migrated": False, "migration_ms": 0.0,
                "pred_latency_ms": float("nan"),
                "real_latency_ms": float("nan"),
                "energy": 0.0, "cpu": 0.0,
                "utility_planned": 0.0, "utility_delivered": 0.0,
                "quality": 0.0, "adaptation": "",
            }
            if loc is None:
                row["outcome"] = "infeasible"
                outcome_rows[w.name] = row
                continue

            if prev_prev is None:
                row["adaptation"] = "Initial Placement"
            else:
                row["adaptation"] = classify_adaptation(
                    prev_loc.value, prev_mode.value, loc.value, mode.value)

            if mode == ExecutionMode.SUSPENDED:
                row["outcome"] = "suspended"
                outcome_rows[w.name] = row
                continue

            migrated = prev_prev is not None and loc != prev_loc
            k = config.MODE_SCALE[mode.value]
            planned_compute = w.compute_requirement * k
            pred_mig = (raw_migration_time_ms(w, prev_loc, loc, system)
                        if migrated else 0.0)
            row["pred_latency_ms"] = (
                planned_compute + network_latency(loc, system)
                + (pred_mig if config.MIGRATION_DOWNTIME_IN_DEADLINE else 0.0))
            row["migrated"] = migrated
            row["utility_planned"] = calculate_utility(w, mode, phase)
            row["quality"] = QUALITY_FACTOR[w.name][mode]

            real_factor = step.real_demand.get(w.name, step.demand[w.name])
            cpu = w.nominal_compute * real_factor * k
            mem = w.memory_requirement * k
            energy = w.nominal_energy * real_factor * k
            host = HOST_OF[loc]
            remote = loc != Location.ONBOARD
            # Only the execution location needs the link: a move to onboard
            # restarts the workload locally (consistent with the planner).
            remote_endpoint = remote

            if not avail[host]["up"]:
                row["outcome"] = "host"
            elif remote_endpoint and not (
                    step.real_connected and _in_coverage(loc, system)):
                row["outcome"] = "link"
            elif (used[host]["cpu"] + cpu > avail[host]["cpu"] + 1e-9
                  or used[host]["mem"] + mem > avail[host]["mem"] + 1e-9
                  or used[host]["energy"] + energy > avail[host]["energy"] + 1e-9):
                row["outcome"] = "resource"
            else:
                used[host]["cpu"] += cpu
                used[host]["mem"] += mem
                used[host]["energy"] += energy
                real_mig = (_realised_migration_ms(
                    w, prev_loc, loc, system, step.real_latency_factor)
                    if migrated else 0.0)
                real_net = network_latency(
                    loc, system,
                    latency_override=system.network.latency
                    * step.real_latency_factor) if remote else 0.0
                latency = cpu + real_net + (
                    real_mig if config.MIGRATION_DOWNTIME_IN_DEADLINE else 0.0)
                row["real_latency_ms"] = latency
                row["migration_ms"] = real_mig
                row["energy"] = energy
                row["cpu"] = cpu
                if latency <= w.deadline:
                    row["outcome"] = "ok"
                    row["utility_delivered"] = row["utility_planned"]
                else:
                    row["outcome"] = "deadline"
            if row["outcome"] != "ok" and migrated and row["migration_ms"] == 0.0:
                row["migration_ms"] = pred_mig
            outcome_rows[w.name] = row

        sim_ns = time.perf_counter_ns() - t1

        stats = getattr(policy, "last_stats", {}) or {}
        step_row = {
            "trial": trial, "policy": policy.name, "t": step.t,
            "scenario": step.scenario, "phase": phase.name,
            "decision_us": decision_ns / 1000.0,
            "simulation_us": sim_ns / 1000.0,
            "onboard_cpu_util": (avail["Onboard"]["bg_cpu"]
                                 + used["Onboard"]["cpu"])
            / config.HOST_CAPACITY["Onboard"][0],
            "onboard_mem_util": (config.HOST_CAPACITY["Onboard"][1]
                                 - avail["Onboard"]["mem"]
                                 + used["Onboard"]["mem"])
            / config.HOST_CAPACITY["Onboard"][1],
            "edge_cpu_util": sum(
                (avail[h]["bg_cpu"] + used[h]["cpu"]) / config.HOST_CAPACITY[h][0]
                for h in ("Edge_1", "Edge_2")) / 2.0,
            "policy_cpu_alloc": sum(used[h]["cpu"] for h in used),
            "connected": step.connected,
            "real_connected": step.real_connected,
            "cloud_up": step.cloud_up,
            "latency_obs": step.values["latency"],
            "position": step.position,
        }
        for key in ("phase1_evaluated", "phase1_feasible", "phase2_evaluated",
                    "phase2_feasible", "catalogue_actions", "nodes_evaluated",
                    "nodes_feasible", "transitions"):
            step_row[key] = stats.get(key, float("nan"))
        steps.append(step_row)
        if record_rows:
            rows.extend(outcome_rows[w.name] for w in system.workloads)

    return rows, steps
