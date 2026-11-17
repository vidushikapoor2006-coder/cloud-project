"""
Run repeated, seeded simulation trials for all policies.

Usage:
    python -m experiments.run_experiments --trials 30 --tag main
    python -m experiments.run_experiments --legacy --tag legacy

Every trial uses one environment trace (seeded) that is shared by all
policies (common random numbers).  Seeds are derived with
numpy.random.SeedSequence(BASE_SEED).spawn(trials) and stored in the
manifest so every trial can be re-run individually.
"""

import argparse
import json
import os
import platform
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from policies import make_policies  # noqa: E402
from simulation.engine import run_episode  # noqa: E402
from simulation.environment import generate_trace, load_network_trace  # noqa: E402

RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def trial_seeds(n, base=None):
    ss = np.random.SeedSequence(config.BASE_SEED if base is None else base)
    return [int(child.generate_state(1)[0]) for child in ss.spawn(n)]


def config_snapshot():
    return {k: (v if isinstance(v, (int, float, str, bool, type(None)))
                else repr(v))
            for k, v in vars(config).items()
            if k.isupper()}


def run(trials, tag, noise=None, profile=None, coverage="default",
        policies=None, network_trace=None, overrides=None, seeds=None,
        quiet=False, policy_factory=None):
    overrides = overrides or {}
    saved = {k: getattr(config, k) for k in overrides}
    for k, v in overrides.items():
        setattr(config, k, v)
    try:
        out_dir = os.path.join(RESULTS_DIR, tag)
        os.makedirs(out_dir, exist_ok=True)
        seeds = seeds or trial_seeds(trials)
        net = load_network_trace(network_trace) if network_trace else None
        all_rows, all_steps = [], []
        t_start = time.time()
        for trial, seed in enumerate(seeds):
            trace = generate_trace(seed, noise=noise, phase_profile=profile,
                                   network_trace=net)
            plist = (policy_factory() if policy_factory
                     else make_policies(include=policies))
            for policy in plist:
                rows, steps = run_episode(policy, trace, trial=trial,
                                          coverage_radius_km=coverage)
                all_rows.extend(rows)
                all_steps.extend(steps)
            if not quiet:
                print(f"[{tag}] trial {trial + 1}/{len(seeds)} done "
                      f"({time.time() - t_start:.1f}s)", flush=True)
        wl = pd.DataFrame(all_rows)
        st = pd.DataFrame(all_steps)
        wl.to_csv(os.path.join(out_dir, "workload_log.csv.gz"), index=False)
        st.to_csv(os.path.join(out_dir, "step_log.csv.gz"), index=False)
        manifest = {
            "tag": tag, "trials": len(seeds), "seeds": seeds,
            "noise": config.NOISE_SCALE if noise is None else noise,
            "phase_profile": profile or config.DEFAULT_PHASE_PROFILE,
            "coverage_radius_km": (config.EDGE_COVERAGE_RADIUS_KM
                                   if coverage == "default" else coverage),
            "overrides": {k: repr(v) for k, v in overrides.items()},
            "network_trace": network_trace,
            "policies": sorted(wl["policy"].unique().tolist()),
            "python": sys.version, "numpy": np.__version__,
            "pandas": pd.__version__, "platform": platform.platform(),
            "processor": platform.processor(),
            "wall_time_s": round(time.time() - t_start, 2),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "config": config_snapshot(),
        }
        with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
            json.dump(manifest, fh, indent=2)
        return wl, st
    finally:
        for k, v in saved.items():
            setattr(config, k, v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=config.NUM_TRIALS)
    ap.add_argument("--tag", default="main")
    ap.add_argument("--noise", type=float, default=None)
    ap.add_argument("--profile", default=None,
                    choices=list(config.PHASE_PROFILES))
    ap.add_argument("--coverage", default="default",
                    help="edge coverage radius in km, 'none' for unlimited")
    ap.add_argument("--policies", default=None,
                    help="comma-separated subset of policy names")
    ap.add_argument("--network-trace", default=None,
                    help="CSV with t,latency_ms,bandwidth,loss_pct,connected")
    ap.add_argument("--ablation", action="store_true",
                    help="component ablation of the proposed policy")
    ap.add_argument("--legacy", action="store_true",
                    help="original deterministic timeline (1 trial, noise 0, "
                         "cruise-only phases, unlimited coverage)")
    a = ap.parse_args()
    coverage = (None if str(a.coverage).lower() == "none"
                else ("default" if a.coverage == "default" else float(a.coverage)))
    policies = a.policies.split(",") if a.policies else None
    if a.ablation:
        from policies import make_ablation_policies
        run(a.trials, a.tag, noise=a.noise, profile=a.profile,
            coverage=coverage, policy_factory=make_ablation_policies)
    elif a.legacy:
        run(1, a.tag, noise=0.0, profile="cruise_only", coverage=None,
            policies=policies, seeds=[0])
    else:
        run(a.trials, a.tag, noise=a.noise, profile=a.profile,
            coverage=coverage, policies=policies,
            network_trace=a.network_trace)


if __name__ == "__main__":
    main()
