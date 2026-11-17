from models.workload import Workload, ExecutionMode
from models.mission import MissionPhase
import config
from orchestrator.feasibility import estimate_latency, get_resource_for_location


# Quality retained by each execution mode
QUALITY_FACTOR = {
    "Obstacle Detection": {
        ExecutionMode.FULL: 1.0,
        ExecutionMode.REDUCED: 0.70,
        ExecutionMode.FALLBACK: 0.60,
        ExecutionMode.SUSPENDED: 0.0
    },

    "Navigation": {
        ExecutionMode.FULL: 1.0,
        ExecutionMode.REDUCED: 0.80,
        ExecutionMode.FALLBACK: 0.60,
        ExecutionMode.SUSPENDED: 0.0
    },

    "Weather Analysis": {
        ExecutionMode.FULL: 1.0,
        ExecutionMode.REDUCED: 0.57,
        ExecutionMode.FALLBACK: 0.25,
        ExecutionMode.SUSPENDED: 0.0
    },

    "Video Analytics": {
        ExecutionMode.FULL: 1.0,
        ExecutionMode.REDUCED: 0.50,
        ExecutionMode.FALLBACK: 0.30,
        ExecutionMode.SUSPENDED: 0.0
    },

    "Flight Logging": {
        ExecutionMode.FULL: 1.0,
        ExecutionMode.REDUCED: 0.50,
        ExecutionMode.FALLBACK: 0.25,
        ExecutionMode.SUSPENDED: 0.0
    }
}


# Mission importance of each workload during each mission phase
MISSION_IMPORTANCE = {
    "Obstacle Detection": {
        MissionPhase.TAKEOFF: 100,
        MissionPhase.CRUISE: 100,
        MissionPhase.APPROACH: 100,
        MissionPhase.LANDING: 100,
        MissionPhase.EMERGENCY: 100
    },

    "Navigation": {
        MissionPhase.TAKEOFF: 100,
        MissionPhase.CRUISE: 100,
        MissionPhase.APPROACH: 100,
        MissionPhase.LANDING: 100,
        MissionPhase.EMERGENCY: 100
    },

    "Weather Analysis": {
        MissionPhase.TAKEOFF: 70,
        MissionPhase.CRUISE: 70,
        MissionPhase.APPROACH: 50,
        MissionPhase.LANDING: 50,
        MissionPhase.EMERGENCY: 20
    },

    "Video Analytics": {
        MissionPhase.TAKEOFF: 50,
        MissionPhase.CRUISE: 50,
        MissionPhase.APPROACH: 70,
        MissionPhase.LANDING: 70,
        MissionPhase.EMERGENCY: 40
    },

    "Flight Logging": {
        MissionPhase.TAKEOFF: 20,
        MissionPhase.CRUISE: 20,
        MissionPhase.APPROACH: 20,
        MissionPhase.LANDING: 20,
        MissionPhase.EMERGENCY: 10
    }
}


def calculate_utility(workload, mode, mission_phase):
    """U_i = B_i(M_t) * q_i(Q_i)  (Eq. (6))."""
    base_utility = MISSION_IMPORTANCE[
        workload.name
    ][mission_phase]

    quality = QUALITY_FACTOR[
        workload.name
    ][mode]

    return base_utility * quality


def calculate_latency_cost(workload, location, mode, system):
    """C^lat = lambda_lat * T_i(a) / D_i  (Eq. (16))."""
    if mode == ExecutionMode.SUSPENDED:
        return 0

    latency = estimate_latency(
        workload,
        location,
        mode,
        system
    )

    # Normalize latency against workload deadline
    normalized_latency = latency / workload.deadline

    return normalized_latency * config.LATENCY_COST_SCALE


def calculate_energy_cost(workload, mode):
    """C^en = lambda_en * kappa(q) * e_i  (Eq. (17))."""
    return (config.ENERGY_COST_SCALE
            * workload.energy_requirement
            * config.MODE_SCALE[mode.value])


def calculate_resource_cost(workload, location, mode, system):
    """C^res = lambda_res * kappa(q) * c_i / CPU capacity of host  (Eq. (18))."""
    if mode == ExecutionMode.SUSPENDED:
        return 0

    resource = get_resource_for_location(location, system)

    if resource is None:
        return 0

    compute = workload.compute_requirement * config.MODE_SCALE[mode.value]

    utilization = compute / resource.cpu_capacity

    return utilization * config.RESOURCE_COST_SCALE


def calculate_score(
    workload,
    location,
    mode,
    system
):
    """Operating score S_i = U_i - C^lat - C^en - C^res  (Eq. (19)).

    The migration cost C^mig is subtracted by the decision layer because it
    depends on the workload's current placement.
    """
    utility = calculate_utility(
        workload,
        mode,
        system.mission.phase
    )

    latency_cost = calculate_latency_cost(
        workload,
        location,
        mode,
        system
    )

    energy_cost = calculate_energy_cost(
        workload,
        mode
    )

    resource_cost = calculate_resource_cost(
        workload,
        location,
        mode,
        system
    )

    score = (
        utility
        - latency_cost
        - energy_cost
        - resource_cost
    )

    return {
        "utility": utility,
        "latency_cost": latency_cost,
        "energy_cost": energy_cost,
        "resource_cost": resource_cost,
        "score": score
    }
