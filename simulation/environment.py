"""
Seeded, time-varying operating environment (Section VI-B of the revised paper).

The original simulator applied one fixed configuration per scenario, so the
system state was constant for ten consecutive steps (Reviewer 2, comment 6).
This module generates, for one trial seed, a complete 80-step trace of

  * observed state  -- what the orchestrator sees at the start of step t
  * realised state  -- what actually happens while the selected actions run

Both are generated BEFORE any policy runs, so every policy is evaluated on
exactly the same trace (common random numbers).

Dynamics (all values in config.py, synthetic, swept in the sensitivity study):
  * scenario targets come from the ORIGINAL scenario functions in
    simulation/scenarios.py; continuous quantities track the target with a
    first-order lag (gradual degradation / gradual recovery) plus Gaussian
    (Ornstein-Uhlenbeck-type) innovations;
  * random contention spikes on the edge nodes;
  * Gilbert-Elliott two-state Markov model of the air-ground link
    (intermittent disconnections) [Gilbert 1960];
  * delayed cloud failure onset and delayed cloud restoration;
  * AR(1) workload demand factors (variable workload demand);
  * deterministic eVTOL trajectory with distance-dependent edge latency and
    edge coverage radius (handover);
  * intra-step deviations between decision and execution (latency jitter,
    demand deviation, background-load deviation, link drop during the step).

With noise=0 and ramp=1 the trace is exactly the original deterministic
timeline (legacy mode).
"""

import csv
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

import config
from models.catalog import create_system
from models.mission import MissionPhase
from simulation.scenarios import (
    normal_conditions, network_degradation, edge_overload, cloud_failure,
    resource_pressure, emergency_mission, severe_degradation, recovery,
)

SCENARIO_FUNCTIONS = {
    "Normal": normal_conditions,
    "Network Degradation": network_degradation,
    "Edge Overload": edge_overload,
    "Cloud Failure": cloud_failure,
    "Resource Pressure": resource_pressure,
    "Emergency Mission": emergency_mission,
    "Severe Degradation": severe_degradation,
    "Recovery": recovery,
}

CONTINUOUS_KEYS = [
    "onboard_cpu", "onboard_mem", "onboard_energy",
    "e1_cpu", "e1_mem", "e2_cpu", "e2_mem",
    "cloud_cpu", "cloud_mem",
    "latency", "bandwidth", "loss",
]


def scenario_targets(name):
    """Target values of a scenario, read from the original scenario function."""
    system = create_system()
    SCENARIO_FUNCTIONS[name](system)
    return {
        "onboard_cpu": system.onboard.cpu_used,
        "onboard_mem": system.onboard.memory_used,
        "onboard_energy": system.onboard.energy_available,
        "e1_cpu": system.edge_1.cpu_used,
        "e1_mem": system.edge_1.memory_used,
        "e2_cpu": system.edge_2.cpu_used,
        "e2_mem": system.edge_2.memory_used,
        "cloud_cpu": system.cloud.cpu_used,
        "cloud_mem": system.cloud.memory_used,
        "latency": system.network.latency,
        "bandwidth": system.network.bandwidth,
        "loss": system.network.packet_loss,
        "connected": system.network.connected,
        "cloud_up": system.cloud.available,
    }


@dataclass
class StepConditions:
    t: int
    scenario: str
    phase: str
    planned_phase: str
    position: float
    values: Dict[str, float]
    connected: bool
    cloud_up: bool
    demand: Dict[str, float]
    # realised (intra-step) deviations
    real_latency_factor: float = 1.0
    real_connected: bool = True
    real_demand: Dict[str, float] = field(default_factory=dict)
    real_bg_delta: Dict[str, float] = field(default_factory=dict)


def scenario_of_step(t):
    return config.SCENARIO_ORDER[t // config.STEPS_PER_SCENARIO]


def load_network_trace(path):
    """Optional trace-driven network input (CSV: t,latency_ms,bandwidth,
    loss_pct,connected).  Rows override the synthetic network targets."""
    rows = {}
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            rows[int(row["t"])] = {
                "latency": float(row["latency_ms"]),
                "bandwidth": float(row["bandwidth"]),
                "loss": float(row["loss_pct"]),
                "connected": str(row["connected"]).strip().lower()
                in ("1", "true", "yes"),
            }
    return rows


def generate_trace(seed, noise=None, ramp=None, phase_profile=None,
                   num_steps=None, network_trace=None,
                   coverage_radius_km="default") -> List[StepConditions]:
    """Generate one reproducible environment trace."""
    noise = config.NOISE_SCALE if noise is None else noise
    ramp = (config.RAMP_RATE if noise > 0 else 1.0) if ramp is None else ramp
    profile = config.PHASE_PROFILES[
        phase_profile or config.DEFAULT_PHASE_PROFILE]
    num_steps = num_steps or config.NUM_STEPS
    rng = np.random.default_rng(seed)

    targets = {name: scenario_targets(name) for name in config.SCENARIO_ORDER}
    state = {k: float(targets["Normal"][k]) for k in CONTINUOUS_KEYS}
    spikes = {"e1": 0.0, "e2": 0.0}
    demand = {s["name"]: 1.0 for s in config.WORKLOAD_SPECS}
    link_good = True
    cloud_onset = int(rng.integers(0, config.CLOUD_FAILURE_ONSET_MAX + 1))
    cloud_return = int(rng.integers(config.CLOUD_RECOVERY_DELAY[0],
                                    config.CLOUD_RECOVERY_DELAY[1] + 1))
    sig = config.OU_SIGMA
    trace = []

    for t in range(num_steps):
        scenario = scenario_of_step(t)
        k_in = t % config.STEPS_PER_SCENARIO
        tgt = dict(targets[scenario])
        if network_trace and t in network_trace:
            tgt.update({k: network_trace[t][k]
                        for k in ("latency", "bandwidth", "loss")})

        # --- continuous quantities: lagged tracking + innovations ---------
        for key in CONTINUOUS_KEYS:
            target = float(tgt[key])
            state[key] = state[key] + ramp * (target - state[key])
            if noise > 0:
                if key == "latency":
                    state[key] += rng.normal(0, sig["latency_rel"] * noise) * target
                elif key == "bandwidth":
                    state[key] += rng.normal(0, sig["bandwidth_rel"] * noise) * target
                elif key == "loss":
                    state[key] += rng.normal(0, sig["loss_abs"] * noise)
                elif key.endswith("_cpu"):
                    state[key] += rng.normal(0, sig["cpu_abs"] * noise)
                elif key.endswith("_mem"):
                    state[key] += rng.normal(0, sig["mem_abs"] * noise)
                elif key == "onboard_energy":
                    state[key] += rng.normal(0, sig["energy_abs"] * noise)
        state["latency"] = max(state["latency"], 1.0)
        state["bandwidth"] = max(state["bandwidth"], 1.0)
        state["loss"] = min(max(state["loss"], 0.0), 95.0)
        state["onboard_energy"] = max(state["onboard_energy"], 0.0)
        for key in CONTINUOUS_KEYS:
            if key.endswith("_cpu") or key.endswith("_mem"):
                host = {"onboard": "Onboard", "e1": "Edge_1", "e2": "Edge_2",
                        "cloud": "AWS_Cloud"}[key.split("_")[0]]
                cap = config.HOST_CAPACITY[host][0 if key.endswith("_cpu") else 1]
                state[key] = min(max(state[key], 0.0), cap)

        values = dict(state)
        # --- edge contention spikes ----------------------------------------
        if noise > 0:
            for e in ("e1", "e2"):
                spikes[e] *= config.CONTENTION_DECAY
                if rng.random() < config.CONTENTION_SPIKE_PROB * min(noise, 1.0):
                    spikes[e] += config.CONTENTION_SPIKE_CPU * noise
                values[f"{e}_cpu"] = min(values[f"{e}_cpu"] + spikes[e], 100.0)

        # --- air-ground link (Gilbert-Elliott) -----------------------------
        if network_trace and t in network_trace:
            connected = network_trace[t]["connected"]
            link_good = connected
        elif noise > 0:
            p_gb, p_bg = config.GE_LINK[scenario]
            if link_good:
                link_good = rng.random() >= p_gb
            else:
                link_good = rng.random() < p_bg
            connected = link_good
        else:
            connected = bool(tgt["connected"])

        # --- cloud availability (delayed failure / delayed recovery) -------
        cloud_up = bool(tgt["cloud_up"])
        if noise > 0:
            if scenario == "Cloud Failure":
                cloud_up = k_in < cloud_onset
            elif scenario == "Recovery":
                cloud_up = k_in >= cloud_return

        # --- workload demand factors (AR(1)) -------------------------------
        if noise > 0:
            lo, hi = config.DEMAND_BOUNDS
            for name in demand:
                demand[name] = min(max(
                    1.0 + config.DEMAND_AR_RHO * (demand[name] - 1.0)
                    + rng.normal(0, config.DEMAND_AR_SIGMA * noise), lo), hi)

        step = StepConditions(
            t=t, scenario=scenario, phase=profile[scenario],
            planned_phase=config.PLANNED_PHASES[scenario],
            position=min(t * config.EVTOL_SPEED_KM_PER_STEP,
                         config.ROUTE_LENGTH_KM),
            values=values, connected=connected, cloud_up=cloud_up,
            demand=dict(demand),
        )

        # --- realised deviations during the step ---------------------------
        if noise > 0:
            step.real_latency_factor = float(math.exp(
                rng.normal(0, config.REALISED_LATENCY_SIGMA * noise)))
            p_gb, p_bg = config.GE_LINK[scenario]
            if connected:
                step.real_connected = rng.random() >= p_gb
            else:
                step.real_connected = rng.random() < p_bg
            step.real_demand = {
                n: demand[n] * float(math.exp(
                    rng.normal(0, config.REALISED_DEMAND_SIGMA * noise)))
                for n in demand}
            step.real_bg_delta = {
                h: float(rng.normal(0, config.REALISED_BG_SIGMA * noise))
                for h in config.HOST_CAPACITY}
        else:
            step.real_connected = connected
            step.real_demand = dict(demand)
            step.real_bg_delta = {h: 0.0 for h in config.HOST_CAPACITY}

        trace.append(step)

    return trace


def apply_observation(system, step: StepConditions, phase_attr="phase"):
    """Write the observed conditions of a step into a SystemState."""
    v = step.values
    system.time = step.t
    system.onboard.cpu_used = v["onboard_cpu"]
    system.onboard.memory_used = v["onboard_mem"]
    system.onboard.energy_available = v["onboard_energy"]
    system.onboard.available = True
    system.edge_1.cpu_used = v["e1_cpu"]
    system.edge_1.memory_used = v["e1_mem"]
    system.edge_1.energy_available = 100
    system.edge_1.available = True
    system.edge_2.cpu_used = v["e2_cpu"]
    system.edge_2.memory_used = v["e2_mem"]
    system.edge_2.energy_available = 100
    system.edge_2.available = True
    system.cloud.cpu_used = v["cloud_cpu"]
    system.cloud.memory_used = v["cloud_mem"]
    system.cloud.energy_available = 100
    system.cloud.available = step.cloud_up
    system.network.latency = v["latency"]
    system.network.bandwidth = v["bandwidth"]
    system.network.packet_loss = v["loss"]
    system.network.connected = step.connected
    phase = MissionPhase[getattr(step, phase_attr)]
    system.mission.phase = phase
    system.mission.emergency = phase == MissionPhase.EMERGENCY
    system.evtol_position = step.position
    for workload in system.workloads:
        workload.set_demand_factor(step.demand[workload.name])
