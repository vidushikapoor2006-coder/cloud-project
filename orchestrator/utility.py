from models.workload import Workload, ExecutionMode
from models.mission import MissionPhase
from orchestrator.feasibility import estimate_latency


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
    base_utility = MISSION_IMPORTANCE[
        workload.name
    ][mission_phase]

    quality = QUALITY_FACTOR[
        workload.name
    ][mode]

    return base_utility * quality


def calculate_latency_cost(workload, location, mode, system):
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

    return normalized_latency * 20


def calculate_energy_cost(workload, mode):
    if mode == ExecutionMode.SUSPENDED:
        return 0

    if mode == ExecutionMode.REDUCED:
        return workload.energy_requirement * 0.5

    if mode == ExecutionMode.FALLBACK:
        return workload.energy_requirement * 0.2

    return workload.energy_requirement


def calculate_resource_cost(workload, location, mode, system):
    if mode == ExecutionMode.SUSPENDED:
        return 0

    resource = None

    if location.value == "Onboard":
        resource = system.onboard

    elif location.value == "Edge_1":
        resource = system.edge_1

    elif location.value == "Edge_2":
        resource = system.edge_2

    elif location.value == "AWS_Cloud":
        resource = system.cloud

    if resource is None:
        return 0

    compute = workload.compute_requirement

    if mode == ExecutionMode.REDUCED:
        compute *= 0.5

    elif mode == ExecutionMode.FALLBACK:
        compute *= 0.2

    utilization = compute / resource.cpu_capacity

    return utilization * 20


def calculate_score(
    workload,
    location,
    mode,
    system
):
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