"""Automated tests for safety constraints, feasibility, migration cost,
utility calculations, metrics and reproducibility (run: python -m pytest)."""

import copy
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from metrics import episode_metrics  # noqa: E402
from models.catalog import create_system  # noqa: E402
from models.mission import MissionPhase  # noqa: E402
from models.workload import ExecutionMode, Location  # noqa: E402
from orchestrator.decision import select_actions_globally  # noqa: E402
from orchestrator.feasibility import (  # noqa: E402
    generate_actions, is_action_feasible, get_feasible_actions,
    network_latency, estimate_latency,
)
from orchestrator.migration import calculate_migration_cost  # noqa: E402
from orchestrator.resource_manager import can_allocate, allocate  # noqa: E402
from orchestrator.utility import (  # noqa: E402
    calculate_utility, calculate_score, MISSION_IMPORTANCE, QUALITY_FACTOR,
)
from policies import make_policies  # noqa: E402
from simulation.engine import run_episode  # noqa: E402
from simulation.environment import (  # noqa: E402
    generate_trace, apply_observation, scenario_targets,
)

FAST = ["Static", "QoS-Based", "Resource-Aware", "Utility-Based",
        "AMC-Adapted", "Elastic-MC", "MDP-Migration", "Proposed-v1", "Proposed"]


def wl(system, name):
    return next(w for w in system.workloads if w.name == name)


@pytest.fixture(scope="module")
def dynamic_runs():
    trace = generate_trace(seed=7, noise=1.0, phase_profile="flight")
    out = {}
    for p in make_policies(include=FAST + ["RH-DP"]):
        rows, steps = run_episode(p, trace, trial=0)
        out[p.name] = (pd.DataFrame(rows), pd.DataFrame(steps))
    return trace, out


# --------------------------------------------------------------- safety ----
def test_catalogue_critical_onboard_only():
    system = create_system()
    for name in config.SAFETY_ONBOARD_ONLY:
        actions = generate_actions(wl(system, name))
        assert actions, name
        assert all(loc == Location.ONBOARD for loc, _ in actions)
        assert all(mode != ExecutionMode.SUSPENDED for _, mode in actions)


def test_explicit_check_rejects_remote_critical():
    system = create_system()
    for name in config.SAFETY_ONBOARD_ONLY:
        for loc in (Location.EDGE_1, Location.EDGE_2, Location.CLOUD):
            assert not is_action_feasible(wl(system, name), loc,
                                          ExecutionMode.FULL, system)


def test_no_policy_offloads_or_suspends_critical(dynamic_runs):
    _, runs = dynamic_runs
    for name, (rows, _) in runs.items():
        crit = rows[rows["critical"]]
        assigned = crit[crit["location"].fillna("") != ""]
        assert (assigned["location"] == "Onboard").all(), name
        assert not (crit["mode"] == "Suspended").any(), name


def test_unservable_critical_is_reported_infeasible_not_offloaded():
    system = create_system()
    system.onboard.cpu_used = 99  # nothing fits onboard
    decisions = select_actions_globally(system)
    for d in decisions:
        if d["workload"] in config.SAFETY_ONBOARD_ONLY:
            assert d["location"] is None


# ---------------------------------------------------------- feasibility ----
@pytest.mark.parametrize("name", FAST[1:])
def test_joint_resource_feasibility(name):
    """Adaptive policies never exceed observed capacity (Eq. (12))."""
    trace = generate_trace(seed=11, noise=1.0)
    policy = make_policies(include=[name])[0]
    system = create_system(coverage_radius_km=config.EDGE_COVERAGE_RADIUS_KM)
    policy.reset()
    for step in trace:
        apply_observation(system, step)
        before = copy.deepcopy(system)
        decisions = policy.decide(system, {"t": step.t, "trace": trace})
        alloc = {}
        for d in decisions:
            if d["location"] is None:
                continue
            w = wl(before, d["workload"])
            assert can_allocate(w, d["location"], d["mode"], before, alloc), \
                (name, step.t, d)
            allocate(w, d["location"], d["mode"], alloc)
            assert is_action_feasible(w, d["location"], d["mode"], before), \
                (name, step.t, d)


def test_packet_loss_and_distance_latency():
    system = create_system()
    system.network.latency = 50
    system.network.packet_loss = 20
    system.evtol_position = 4.0
    assert network_latency(Location.ONBOARD, system) == 0.0
    assert network_latency(Location.CLOUD, system) == pytest.approx(50 / 0.8)
    assert network_latency(Location.EDGE_1, system) == pytest.approx(70 / 0.8)
    assert network_latency(Location.EDGE_2, system) == pytest.approx(80 / 0.8)
    w = wl(system, "Weather Analysis")
    assert estimate_latency(w, Location.CLOUD, ExecutionMode.REDUCED, system) \
        == pytest.approx(10 + 50 / 0.8)


def test_edge_coverage():
    system = create_system(coverage_radius_km=8.0)
    w = wl(system, "Weather Analysis")
    system.evtol_position = 9.0
    assert not is_action_feasible(w, Location.EDGE_1, ExecutionMode.FULL, system)
    system.evtol_position = 7.0
    assert is_action_feasible(w, Location.EDGE_1, ExecutionMode.FULL, system)


# ------------------------------------------------------------ migration ----
def test_migration_cost_formula():
    system = create_system()
    w = wl(system, "Video Analytics")
    w.previous_location = Location.ONBOARD
    w.current_location = Location.ONBOARD
    m = calculate_migration_cost(w, Location.ONBOARD, Location.CLOUD, system)
    # 1 MB / 50 MB/s = 20 ms + 50 ms latency + 5 ms overhead
    assert m["migration_time_ms"] == pytest.approx(75.0)
    assert m["migration_cost"] == pytest.approx(75.0 / 150.0 * 20.0)
    m2 = calculate_migration_cost(w, Location.EDGE_1, Location.EDGE_2, system)
    assert m2["migration_time_ms"] == pytest.approx(20 + 20 + 5)
    system.network.bandwidth = 10
    m3 = calculate_migration_cost(w, Location.EDGE_1, Location.CLOUD, system)
    assert m3["migration_time_ms"] == pytest.approx(100 + 50 + 5)


def test_initial_placement_is_not_migration():
    system = create_system()
    w = wl(system, "Video Analytics")
    assert w.previous_location is None
    m = calculate_migration_cost(w, Location.ONBOARD, Location.CLOUD, system)
    assert m["migration_time_ms"] == 0.0 and m["migration_cost"] == 0.0


# -------------------------------------------------------------- utility ----
def test_utility_values():
    system = create_system()
    v = wl(system, "Video Analytics")
    assert calculate_utility(v, ExecutionMode.REDUCED,
                             MissionPhase.EMERGENCY) == pytest.approx(20.0)
    assert calculate_utility(v, ExecutionMode.SUSPENDED,
                             MissionPhase.CRUISE) == 0.0
    for name, table in MISSION_IMPORTANCE.items():
        for phase in MissionPhase:
            assert phase in table
        q = QUALITY_FACTOR[name]
        assert q[ExecutionMode.FULL] >= q[ExecutionMode.REDUCED] \
            >= q[ExecutionMode.FALLBACK] >= q[ExecutionMode.SUSPENDED] == 0


def test_score_components():
    system = create_system()
    w = wl(system, "Weather Analysis")
    r = calculate_score(w, Location.CLOUD, ExecutionMode.FULL, system)
    lat = 20 + 50 / 0.99
    assert r["latency_cost"] == pytest.approx(lat / 200 * 20)
    assert r["energy_cost"] == pytest.approx(8)
    assert r["resource_cost"] == pytest.approx(20 / 200 * 20)
    assert r["score"] == pytest.approx(
        70 - r["latency_cost"] - r["energy_cost"] - r["resource_cost"])


def test_phase2_is_lexicographic_utility_first():
    """Every non-critical choice of Proposed has maximal utility among the
    actions that fit in the residual resources (Eq. (20))."""
    trace = generate_trace(seed=3, noise=1.0)
    system = create_system(coverage_radius_km=config.EDGE_COVERAGE_RADIUS_KM)
    for step in trace:
        apply_observation(system, step)
        before = copy.deepcopy(system)
        decisions = select_actions_globally(system)
        alloc = {}
        for d in decisions:  # decisions are in commit order
            if d["location"] is None:
                continue
            w = wl(before, d["workload"])
            if w.name not in config.SAFETY_ONBOARD_ONLY:
                best_u = max(
                    calculate_utility(w, m, before.mission.phase)
                    for loc, m in get_feasible_actions(w, before)
                    if can_allocate(w, loc, m, before, alloc))
                assert calculate_utility(w, d["mode"], before.mission.phase) \
                    == pytest.approx(best_u)
            allocate(w, d["location"], d["mode"], alloc)


def test_phase2_order_follows_phase_importance():
    system = create_system()
    system.mission.phase = MissionPhase.EMERGENCY
    decisions = select_actions_globally(system)
    names = [d["workload"] for d in decisions][2:]
    assert names == ["Video Analytics", "Weather Analysis", "Flight Logging"]


def test_critical_margin_reserves_headroom():
    system = create_system()
    system.onboard.cpu_used = 100 - 66  # OD 30 + Nav 35 = 65 fits exactly
    d0 = select_actions_globally(copy.deepcopy(system), margin=0.0)
    d1 = select_actions_globally(copy.deepcopy(system), margin=0.2)
    m0 = {d["workload"]: d["mode"] for d in d0}
    m1 = {d["workload"]: d["mode"] for d in d1}
    assert m0["Obstacle Detection"] == ExecutionMode.FULL
    assert m0["Navigation"] == ExecutionMode.FULL
    assert ExecutionMode.FULL not in (m1["Obstacle Detection"],
                                      m1["Navigation"]) or \
        m1["Obstacle Detection"] != m1["Navigation"]


# ------------------------------------------------------ mixed criticality ----
def test_amc_drops_lo_in_hi_mode():
    system = create_system()
    system.onboard.cpu_used = 70  # HI workloads cannot both run Full
    policy = make_policies(include=["AMC-Adapted"])[0]
    decisions = policy.decide(system)
    assert policy.mode == "HI"
    for d in decisions:
        if d["workload"] not in config.SAFETY_ONBOARD_ONLY and d["mode"]:
            assert d["mode"] == ExecutionMode.SUSPENDED


# -------------------------------------------------------------- metrics ----
def test_metrics_separate_assignment_from_execution():
    rows = []
    for t in range(4):
        for name, crit in (("Obstacle Detection", True), ("Navigation", True)):
            ok = not (name == "Navigation" and t < 2)
            rows.append({"trial": 0, "policy": "X", "t": t, "scenario": "S",
                         "phase": "CRUISE", "workload": name, "critical": crit,
                         "location": "Onboard", "mode": "Full",
                         "outcome": "ok" if ok else "resource",
                         "migrated": False, "migration_ms": 0.0,
                         "energy": 1.0, "utility_planned": 100.0,
                         "utility_delivered": 100.0 if ok else 0.0,
                         "adaptation": "No Change"})
    st = pd.DataFrame([{"trial": 0, "policy": "X", "t": t, "decision_us": 1.0,
                        "onboard_cpu_util": 0.5, "onboard_mem_util": 0.5,
                        "edge_cpu_util": 0.5} for t in range(4)])
    m = episode_metrics(pd.DataFrame(rows), st).iloc[0]
    assert m["crit_non_suspension"] == 1.0          # old "preservation"
    assert m["crit_exec_success"] == pytest.approx(6 / 8)
    assert m["deadline_miss_ratio"] == pytest.approx(2 / 8)
    assert m["utility_delivered"] == 600 and m["utility_planned"] == 800


def test_static_non_suspension_differs_from_success(dynamic_runs):
    _, runs = dynamic_runs
    rows, steps = runs["Static"]
    m = episode_metrics(rows, steps).iloc[0]
    assert m["crit_non_suspension"] == 1.0
    assert m["crit_exec_success"] < 1.0


# ------------------------------------------------------ reproducibility ----
def test_trace_is_reproducible():
    a = generate_trace(seed=5)
    b = generate_trace(seed=5)
    c = generate_trace(seed=6)
    assert [s.values for s in a] == [s.values for s in b]
    assert [s.connected for s in a] == [s.connected for s in b]
    assert [s.values for s in a] != [s.values for s in c]


def test_episode_is_reproducible():
    trace = generate_trace(seed=9)
    p = make_policies(include=["Proposed"])[0]
    r1 = pd.DataFrame(run_episode(p, trace)[0])
    r2 = pd.DataFrame(run_episode(p, trace)[0])
    cols = ["location", "mode", "outcome", "utility_delivered"]
    assert r1[cols].equals(r2[cols])


def test_legacy_trace_equals_original_scenarios():
    trace = generate_trace(seed=0, noise=0.0, phase_profile="cruise_only")
    for step in trace:
        tgt = scenario_targets(step.scenario)
        for k, v in step.values.items():
            assert v == pytest.approx(tgt[k]), (step.t, k)
        assert step.connected == tgt["connected"]
        assert step.cloud_up == tgt["cloud_up"]


def test_dynamic_conditions_vary_within_scenarios():
    trace = generate_trace(seed=1)
    for s0 in range(0, config.NUM_STEPS, config.STEPS_PER_SCENARIO):
        lat = [trace[t].values["latency"] for t in range(s0, s0 + 10)]
        assert len(set(np.round(lat, 6))) > 5


def test_legacy_emergency_regression():
    """Original policy loses in Emergency; revised policy does not."""
    trace = generate_trace(seed=0, noise=0.0, phase_profile="cruise_only")
    res = {}
    for p in make_policies(include=["Utility-Based", "Proposed-v1", "Proposed"]):
        rows = pd.DataFrame(run_episode(p, trace, coverage_radius_km=None)[0])
        res[p.name] = rows[rows["scenario"] == "Emergency Mission"][
            "utility_delivered"].sum()
    assert res["Proposed-v1"] < res["Utility-Based"]
    assert res["Proposed"] >= res["Utility-Based"]


def test_lookahead_runs_and_respects_safety(dynamic_runs):
    _, runs = dynamic_runs
    rows, steps = runs["RH-DP"]
    assert len(rows) == 5 * config.NUM_STEPS
    assert steps["decision_us"].gt(0).all()


# ------------------------------------------------------------- ablation ----
def test_ablation_variants_respect_constraints():
    from policies import make_ablation_policies
    trace = generate_trace(seed=13, noise=1.0)
    for policy in make_ablation_policies():
        rows = pd.DataFrame(run_episode(policy, trace)[0])
        crit = rows[rows["critical"]]
        assigned = crit[crit["location"].fillna("") != ""]
        assert (assigned["location"] == "Onboard").all(), policy.name
        assert not (crit["mode"] == "Suspended").any(), policy.name
        if policy.name == "Abl-NoDegradation":
            assert set(rows["mode"].fillna("")) <= {"Full", "Suspended", ""}


def test_ablation_default_equals_full_policy():
    from orchestrator.decision import ABLATION_DEFAULTS
    trace = generate_trace(seed=21, noise=1.0)
    full = pd.DataFrame(run_episode(make_policies(include=["Proposed"])[0], trace)[0])
    from policies import ProposedPolicy
    same = pd.DataFrame(run_episode(
        ProposedPolicy("revised", name="Proposed", ablation=dict(ABLATION_DEFAULTS)),
        trace)[0])
    cols = ["location", "mode", "outcome"]
    assert full[cols].equals(same[cols])


def test_phase_blind_restores_true_phase():
    system = create_system()
    system.mission.phase = MissionPhase.EMERGENCY
    select_actions_globally(system, ablation={"phase_aware": False})
    assert system.mission.phase == MissionPhase.EMERGENCY


def test_mdp_migration_value_function_finite_onboard():
    p = make_policies(include=["MDP-Migration"])[0]
    system = create_system(coverage_radius_km=config.EDGE_COVERAGE_RADIUS_KM)
    p.decide(system)
    V = p._values["Video Analytics"]
    assert all(math.isfinite(V[t][Location.ONBOARD]) for t in range(len(V) - 1))
    # Edge_2 (at 10 km) is out of coverage (R = 8 km) at the route start
    assert math.isinf(V[0][Location.EDGE_2])
