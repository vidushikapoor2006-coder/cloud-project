"""
Decision-latency benchmark and complexity evidence (Reviewer 2, comment 4).

Part A -- repeated decisions on recorded states.
    For one seeded trace, the system state that each policy observes at every
    step is captured (deep copy, including the policy's internal state).  Each
    state is then decided R times; only policy.decide() is timed
    (time.perf_counter_ns).  Copying, simulation and logging are excluded.

Part B -- counted combinations of the proposed policy per step:
    catalogue actions screened, Phase-1 combinations evaluated / feasible,
    Phase-2 actions evaluated / feasible.

Part C -- scaling with the number of workloads (synthetic clones of the
    critical and non-critical workloads on enlarged hosts), to expose the
    exponential term (critical joint enumeration) and the linear term.

Part D -- theoretical action-space sizes.

Outputs: results/runtime/*.csv
"""

import copy
import os
import statistics
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from experiments.run_experiments import RESULTS_DIR, trial_seeds  # noqa: E402
from models.catalog import create_system  # noqa: E402
from models.workload import ExecutionMode, Location  # noqa: E402
from orchestrator.decision import select_actions_globally  # noqa: E402
from orchestrator.feasibility import generate_actions  # noqa: E402
from policies import make_policies, POLICY_ORDER  # noqa: E402
from simulation.environment import generate_trace, apply_observation  # noqa: E402

OUT = os.path.join(RESULTS_DIR, "runtime")


def capture_states(policy, trace):
    system = create_system(coverage_radius_km=config.EDGE_COVERAGE_RADIUS_KM)
    policy.reset()
    states = []
    for step in trace:
        apply_observation(system, step)
        states.append((copy.deepcopy(system), copy.deepcopy(policy), step.t))
        policy.decide(system, {"t": step.t, "trace": trace})
    return states


def part_a(trace, reps):
    rows, counts = [], []
    for policy in make_policies():
        r = max(2, reps // 10) if policy.name.startswith("RH-DP") else reps
        states = capture_states(policy, trace)
        samples = []
        for system, pol, t in states:
            for _ in range(r):
                s = copy.deepcopy(system)
                p = copy.deepcopy(pol)
                t0 = time.perf_counter_ns()
                p.decide(s, {"t": t, "trace": trace})
                samples.append((time.perf_counter_ns() - t0) / 1000.0)
                if policy.name in ("Proposed", "RH-DP") and _ == 0:
                    counts.append(dict(policy=policy.name, t=t,
                                       **getattr(p, "last_stats", {})))
        a = np.array(samples)
        rows.append({"policy": policy.name, "states": len(states),
                     "repetitions": r, "samples": len(a),
                     "mean_us": a.mean(), "sd_us": a.std(ddof=1),
                     "min_us": a.min(), "median_us": np.median(a),
                     "p95_us": np.percentile(a, 95), "max_us": a.max()})
        print(policy.name, round(a.mean(), 1), "us", flush=True)
    return pd.DataFrame(rows), pd.DataFrame(counts)


def scaled_system(n_crit, n_non):
    base = create_system(coverage_radius_km=None)
    crit = [w for w in base.workloads if w.criticality.name == "VERY_HIGH"]
    non = [w for w in base.workloads if w.criticality.name != "VERY_HIGH"]
    workloads = []
    for i in range(n_crit):
        w = copy.deepcopy(crit[i % len(crit)])
        workloads.append(w)
    for i in range(n_non):
        w = copy.deepcopy(non[i % len(non)])
        workloads.append(w)
    base.workloads = workloads
    # Enlarge hosts so that the problem stays feasible as it grows.
    scale = max(1.0, (n_crit + n_non) / 5.0)
    for r in (base.onboard, base.edge_1, base.edge_2, base.cloud):
        r.cpu_capacity *= scale * 1.5
        r.memory_capacity *= scale * 1.5
        r.energy_available *= scale * 1.5
    return base


def part_c(reps):
    rows = []
    for n_crit in (1, 2, 3, 4, 5, 6):
        for n_non in (3, 6, 12, 24, 48):
            system = scaled_system(n_crit, n_non)
            samples = []
            stats = {}
            for _ in range(reps):
                s = copy.deepcopy(system)
                t0 = time.perf_counter_ns()
                select_actions_globally(s, stats)
                samples.append((time.perf_counter_ns() - t0) / 1000.0)
            a = np.array(samples)
            rows.append({"n_critical": n_crit, "n_noncritical": n_non,
                         "mean_us": a.mean(), "p95_us": np.percentile(a, 95),
                         **{k: stats[k] for k in stats}})
        print("scaling n_crit", n_crit, "done", flush=True)
    return pd.DataFrame(rows)


def part_d():
    system = create_system()
    n_loc, n_mode = len(Location), len(ExecutionMode)
    sizes = [len(generate_actions(w)) for w in system.workloads]
    orig = {"Obstacle Detection": 7, "Navigation": 7, "Weather Analysis": 10,
            "Video Analytics": 11, "Flight Logging": 10}
    crit_opts = [sizes[i] + 1 for i, w in enumerate(system.workloads)
                 if w.name in config.SAFETY_ONBOARD_ONLY]
    return pd.DataFrame([
        {"quantity": "unrestricted joint action space (|L||Q|)^N",
         "value": (n_loc * n_mode) ** len(system.workloads)},
        {"quantity": "original catalogue joint space prod|A_i|",
         "value": int(np.prod(list(orig.values())))},
        {"quantity": "revised (safety) catalogue joint space prod|A_i|",
         "value": int(np.prod(sizes))},
        {"quantity": "catalogue actions screened per step sum|A_i|",
         "value": int(sum(sizes))},
        {"quantity": "Phase-1 combinations enumerated prod(|A_c|+1)",
         "value": int(np.prod(crit_opts))},
        {"quantity": "Phase-2 single-action evaluations (upper bound)",
         "value": int(sum(s for s, w in zip(sizes, system.workloads)
                          if w.name not in config.SAFETY_ONBOARD_ONLY))},
    ])


def main(reps=50):
    os.makedirs(OUT, exist_ok=True)
    seed = trial_seeds(1)[0]
    trace = generate_trace(seed)
    a, counts = part_a(trace, reps)
    a.to_csv(os.path.join(OUT, "decision_latency_repeated.csv"), index=False)
    counts.to_csv(os.path.join(OUT, "combination_counts.csv"), index=False)
    part_c(20).to_csv(os.path.join(OUT, "scaling.csv"), index=False)
    part_d().to_csv(os.path.join(OUT, "action_space.csv"), index=False)
    with open(os.path.join(OUT, "environment.txt"), "w") as fh:
        import platform
        fh.write(f"python {sys.version}\nplatform {platform.platform()}\n"
                 f"processor {platform.processor()}\ncpus {os.cpu_count()}\n"
                 f"seed {seed}\nrepetitions {reps}\n")
    print("runtime results in", OUT)


if __name__ == "__main__":
    main()
