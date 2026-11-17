"""
Central parameter registry for the eVTOL cloud-edge orchestration simulator.

Every numeric parameter used by the simulator, the orchestration policies and
the experiment pipeline is defined here exactly once. The LaTeX parameter
tables of the revised manuscript are generated from this file by
``experiments/make_tables.py`` so that the paper and the code cannot drift.

Parameter categories (column "Type" in the paper tables):
    fixed        -- constant for the whole experiment
    dynamic      -- evolves over time inside the simulator (value = nominal/target)
    varied       -- swept in the sensitivity analysis
    derived      -- computed from other parameters at run time

Source column:
    "orig. code" -- value taken unchanged from the originally submitted code
    "this rev."  -- synthetic modelling value introduced in this revision to
                    make the simulation dynamic; documented and swept in the
                    sensitivity analysis. These are NOT measured values.

Units: CPU, memory and energy are expressed in *normalised units* (the
onboard computer has 100 CPU units and 100 memory units).  Latency and
deadlines are in milliseconds.  Bandwidth values are in MB/s, which is the
unit implied by the original migration model (state size in MB divided by a
bandwidth of 50).  Physical calibration of these units is listed as an open
item in ACTIONS_REQUIRED.md.
"""

import math

# ---------------------------------------------------------------------------
# Workloads (orig. code: main.py / comparison.py create_system())
# ---------------------------------------------------------------------------
# name, criticality level, deadline D_i [ms], CPU c_i, memory m_i,
# energy e_i, network requirement b_i [MB/s], state size s_i [MB]
WORKLOAD_SPECS = [
    dict(name="Obstacle Detection", criticality="VERY_HIGH", deadline=50,
         cpu=30, memory=20, energy=15, network=10, state_mb=1.0),
    dict(name="Navigation", criticality="VERY_HIGH", deadline=50,
         cpu=35, memory=25, energy=15, network=10, state_mb=1.0),
    dict(name="Weather Analysis", criticality="HIGH", deadline=200,
         cpu=20, memory=15, energy=8, network=20, state_mb=1.0),
    dict(name="Video Analytics", criticality="MEDIUM", deadline=150,
         cpu=30, memory=20, energy=10, network=30, state_mb=1.0),
    dict(name="Flight Logging", criticality="LOW", deadline=500,
         cpu=10, memory=10, energy=3, network=5, state_mb=1.0),
]

# Safety restriction (this revision, Reviewer 2 comment 9): flight-critical
# workloads may execute ONLY on the onboard computer, for every policy.
SAFETY_ONBOARD_ONLY = ("Obstacle Detection", "Navigation")

# ---------------------------------------------------------------------------
# Service modes (orig. code: orchestrator/resource_manager.py)
# kappa(q): resource / compute-time scaling of each execution mode
# ---------------------------------------------------------------------------
MODE_SCALE = {"Full": 1.0, "Reduced": 0.5, "Fallback": 0.2, "Suspended": 0.0}

# ---------------------------------------------------------------------------
# Hosts (orig. code)
# ---------------------------------------------------------------------------
HOST_CAPACITY = {
    # cpu capacity, memory capacity
    "Onboard": (100, 100),
    "Edge_1": (100, 100),
    "Edge_2": (100, 100),
    "AWS_Cloud": (200, 200),
}
EDGE_POSITIONS_KM = {"Edge_1": 0.0, "Edge_2": 10.0}      # orig. code
DISTANCE_LATENCY_MS_PER_KM = 5.0                           # orig. code
EVTOL_SPEED_KM_PER_STEP = 0.125                            # orig. code
ROUTE_LENGTH_KM = 10.0                                     # orig. code

# Edge radio coverage radius (this rev., synthetic; varied in sensitivity).
# Each edge node is reachable only while the eVTOL is within this distance.
EDGE_COVERAGE_RADIUS_KM = 8.0

# ---------------------------------------------------------------------------
# Utility / cost coefficients (orig. code: orchestrator/utility.py)
# ---------------------------------------------------------------------------
LATENCY_COST_SCALE = 20.0       # lambda_lat
RESOURCE_COST_SCALE = 20.0      # lambda_res
ENERGY_COST_SCALE = 1.0         # lambda_en (energy cost = e_i * kappa(q))

# ---------------------------------------------------------------------------
# Migration model (orig. code: orchestrator/decision.py)
# ---------------------------------------------------------------------------
MIGRATION_BANDWIDTH = 50.0      # B_mig [MB/s]
EDGE_TO_EDGE_LATENCY_MS = 20.0  # L_EE [ms]
MIGRATION_OVERHEAD_MS = 5.0     # T_orch [ms]
MIGRATION_COST_SCALE = 20.0     # lambda_mig
# Migration downtime model.  False (default, as in the original model):
# pre-copy/live migration -- the state transfer overlaps with service, so
# T_mig is a soft cost C^mig and is not added to the response time.
# True (sensitivity variant): cold migration -- T_mig is added to the
# response time of the migrating step and must satisfy T_i + T_mig <= D_i.
MIGRATION_DOWNTIME_IN_DEADLINE = False

# Critical-admission headroom delta (this rev.; varied in sensitivity).
# Phase 1 of the proposed policy admits flight-critical workloads with the
# pessimistic budget (1 + delta) * c_i, analogous to the C(HI) budget of
# mixed-criticality scheduling [Vestal 2007].  0 = original algorithm.
CRITICAL_DEMAND_MARGIN = 0.0

# ---------------------------------------------------------------------------
# Simulation timeline (orig. code: simulation/timeline.py)
# ---------------------------------------------------------------------------
SCENARIO_ORDER = [
    "Normal", "Network Degradation", "Edge Overload", "Cloud Failure",
    "Resource Pressure", "Emergency Mission", "Severe Degradation", "Recovery",
]
STEPS_PER_SCENARIO = 10
NUM_STEPS = STEPS_PER_SCENARIO * len(SCENARIO_ORDER)

# Mission-phase profile (this rev.).  The original code used CRUISE for every
# scenario except "Emergency Mission".  The revision follows a flight profile
# so that the Takeoff/Approach/Landing importance values defined in the
# original utility table are actually exercised.  "cruise_only" reproduces
# the original behaviour and is evaluated in the sensitivity analysis.
PHASE_PROFILES = {
    "flight": {
        "Normal": "TAKEOFF",
        "Network Degradation": "CRUISE",
        "Edge Overload": "CRUISE",
        "Cloud Failure": "CRUISE",
        "Resource Pressure": "CRUISE",
        "Emergency Mission": "EMERGENCY",
        "Severe Degradation": "APPROACH",
        "Recovery": "LANDING",
    },
    "cruise_only": {s: ("EMERGENCY" if s == "Emergency Mission" else "CRUISE")
                    for s in SCENARIO_ORDER},
}
DEFAULT_PHASE_PROFILE = "flight"

# The flight plan known in advance (used ONLY by the look-ahead policies as
# their forecast).  Emergencies are not known in advance, so the planned
# phase during steps 50-59 is CRUISE.
PLANNED_PHASES = dict(PHASE_PROFILES["flight"], **{"Emergency Mission": "CRUISE"})

# ---------------------------------------------------------------------------
# Stochastic dynamics (this rev., synthetic; all scaled by NOISE_SCALE)
# ---------------------------------------------------------------------------
NOISE_SCALE = 1.0               # varied in sensitivity: 0 = deterministic
RAMP_RATE = 0.5                 # first-order tracking of scenario targets per step
OU_SIGMA = {                    # per-step Gaussian innovation (std. dev.)
    "latency_rel": 0.10,        # relative to target
    "bandwidth_rel": 0.10,
    "loss_abs": 1.5,            # packet-loss percentage points
    "cpu_abs": 4.0,             # background CPU units
    "mem_abs": 3.0,             # background memory units
    "energy_abs": 4.0,          # onboard energy units per step
}
CONTENTION_SPIKE_PROB = 0.10    # per edge per step
CONTENTION_SPIKE_CPU = 15.0     # added background CPU units on a spike
CONTENTION_DECAY = 0.5          # spike decay per step
DEMAND_AR_RHO = 0.7             # AR(1) coefficient of workload demand factor
DEMAND_AR_SIGMA = 0.05
DEMAND_BOUNDS = (0.8, 1.3)
# Intra-step (decision-to-execution) deviations
REALISED_LATENCY_SIGMA = 0.10   # log-normal sigma of realised network latency
REALISED_DEMAND_SIGMA = 0.05    # log-normal sigma of realised compute demand
REALISED_BG_SIGMA = 2.0         # background CPU deviation [units]
# Gilbert-Elliott air-ground link: P(good->bad), P(bad->good) per step.
GE_LINK = {
    "Normal": (0.02, 0.60),
    "Network Degradation": (0.15, 0.40),
    "Edge Overload": (0.02, 0.60),
    "Cloud Failure": (0.02, 0.60),
    "Resource Pressure": (0.08, 0.50),
    "Emergency Mission": (0.02, 0.60),
    "Severe Degradation": (0.70, 0.15),
    "Recovery": (0.05, 0.60),
}
CLOUD_FAILURE_ONSET_MAX = 2     # cloud fails within the first 0..2 steps
CLOUD_RECOVERY_DELAY = (1, 3)   # cloud returns 1..3 steps into Recovery

# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------
NUM_TRIALS = 30
BASE_SEED = 20260909            # orig. code (robustness_evaluation.py)
LOOKAHEAD_HORIZON = 5           # H (steps)
LOOKAHEAD_TOP_M = 4             # candidate actions per non-critical workload


def edge_in_coverage(location_value, position_km, radius_km=None):
    radius = EDGE_COVERAGE_RADIUS_KM if radius_km is None else radius_km
    if radius is None or math.isinf(radius):
        return True
    return abs(position_km - EDGE_POSITIONS_KM[location_value]) <= radius + 1e-9
