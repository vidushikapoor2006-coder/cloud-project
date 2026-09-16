from models.workload import Workload, Location, ExecutionMode
from models.state import SystemState

def generate_actions(workload: Workload):

    actions = []

    if workload.name == "Obstacle Detection":
        actions = [
            (Location.ONBOARD, ExecutionMode.FULL),
            (Location.EDGE_1, ExecutionMode.FULL),
            (Location.EDGE_2, ExecutionMode.FULL),

            (Location.ONBOARD, ExecutionMode.REDUCED),
            (Location.EDGE_1, ExecutionMode.REDUCED),
            (Location.EDGE_2, ExecutionMode.REDUCED),

            (Location.ONBOARD, ExecutionMode.FALLBACK)
        ]

    elif workload.name == "Navigation":
        actions = [
            (Location.ONBOARD, ExecutionMode.FULL),
            (Location.EDGE_1, ExecutionMode.FULL),
            (Location.EDGE_2, ExecutionMode.FULL),

            (Location.ONBOARD, ExecutionMode.REDUCED),
            (Location.EDGE_1, ExecutionMode.REDUCED),
            (Location.EDGE_2, ExecutionMode.REDUCED),

            (Location.ONBOARD, ExecutionMode.FALLBACK)
        ]

    elif workload.name == "Weather Analysis":
        actions = [
            (Location.EDGE_1, ExecutionMode.FULL),
            (Location.EDGE_2, ExecutionMode.FULL),
            (Location.CLOUD, ExecutionMode.FULL),

            (Location.EDGE_1, ExecutionMode.REDUCED),
            (Location.EDGE_2, ExecutionMode.REDUCED),
            (Location.CLOUD, ExecutionMode.REDUCED),

            (Location.ONBOARD, ExecutionMode.FALLBACK),

            (Location.EDGE_1, ExecutionMode.SUSPENDED),
            (Location.EDGE_2, ExecutionMode.SUSPENDED),
            (Location.CLOUD, ExecutionMode.SUSPENDED)
        ]

    elif workload.name == "Video Analytics":
        actions = [
            (Location.EDGE_1, ExecutionMode.FULL),
            (Location.EDGE_2, ExecutionMode.FULL),
            (Location.CLOUD, ExecutionMode.FULL),

            (Location.ONBOARD, ExecutionMode.REDUCED),
            (Location.EDGE_1, ExecutionMode.REDUCED),
            (Location.EDGE_2, ExecutionMode.REDUCED),
            (Location.CLOUD, ExecutionMode.REDUCED),

            (Location.ONBOARD, ExecutionMode.FALLBACK),

            (Location.EDGE_1, ExecutionMode.SUSPENDED),
            (Location.EDGE_2, ExecutionMode.SUSPENDED),
            (Location.CLOUD, ExecutionMode.SUSPENDED)
        ]

    elif workload.name == "Flight Logging":
        actions = [
            (Location.EDGE_1, ExecutionMode.FULL),
            (Location.EDGE_2, ExecutionMode.FULL),
            (Location.CLOUD, ExecutionMode.FULL),

            (Location.EDGE_1, ExecutionMode.REDUCED),
            (Location.EDGE_2, ExecutionMode.REDUCED),
            (Location.CLOUD, ExecutionMode.REDUCED),

            (Location.ONBOARD, ExecutionMode.FALLBACK),

            (Location.EDGE_1, ExecutionMode.SUSPENDED),
            (Location.EDGE_2, ExecutionMode.SUSPENDED),
            (Location.CLOUD, ExecutionMode.SUSPENDED)
        ]

    return actions

def get_resource_for_location(
    location: Location,
    system: SystemState
):
    if location == Location.ONBOARD:
        return system.onboard

    if location == Location.EDGE_1:
        return system.edge_1

    if location == Location.EDGE_2:
        return system.edge_2

    if location == Location.CLOUD:
        return system.cloud

    return None

def has_enough_resources(
    workload: Workload,
    location: Location,
    mode: ExecutionMode,
    system: SystemState
):
    resource = get_resource_for_location(location, system)

    if resource is None:
        return False

    if not resource.available:
        return False

    compute_requirement = workload.compute_requirement
    memory_requirement = workload.memory_requirement

    # Reduced mode needs fewer resources
    if mode == ExecutionMode.REDUCED:
        compute_requirement *= 0.5
        memory_requirement *= 0.5

    # Fallback is lightweight
    elif mode == ExecutionMode.FALLBACK:
        compute_requirement *= 0.2
        memory_requirement *= 0.2

    # Suspended workload uses no execution resources
    elif mode == ExecutionMode.SUSPENDED:
        return True

    if resource.cpu_available < compute_requirement:
        return False

    if resource.memory_available < memory_requirement:
        return False

    return True

def network_is_feasible(
    workload: Workload,
    location: Location,
    system: SystemState
):
    # Onboard execution does not require external network
    if location == Location.ONBOARD:
        return True

    network = system.network

    # No connection means remote execution is impossible
    if not network.connected:
        return False

    # Check bandwidth requirement
    if network.bandwidth < workload.network_requirement:
        return False

    return True

def estimate_latency(
    workload: Workload,
    location: Location,
    mode: ExecutionMode,
    system: SystemState
):
    # Base computation latency
    compute_latency = workload.compute_requirement

    if mode == ExecutionMode.REDUCED:
        compute_latency *= 0.5

    elif mode == ExecutionMode.FALLBACK:
        compute_latency *= 0.2

    elif mode == ExecutionMode.SUSPENDED:
        return 0

    # Onboard has no network latency
    if location == Location.ONBOARD:
        return compute_latency

    # Remote execution
    base_latency = system.network.latency

    # Mobility-aware latency for Edge 1 and Edge 2
    if location.value == "Edge_1":
        distance = abs(system.evtol_position - 0.0)
        network_latency = base_latency + (distance * 5)

    elif location.value == "Edge_2":
        distance = abs(system.evtol_position - 10.0)
        network_latency = base_latency + (distance * 5)

    else:
        # Cloud keeps the existing network latency
        network_latency = base_latency

    return compute_latency + network_latency

def meets_deadline(
    workload: Workload,
    location: Location,
    mode: ExecutionMode,
    system: SystemState
):
    if mode == ExecutionMode.SUSPENDED:
        return True

    latency = estimate_latency(
        workload,
        location,
        mode,
        system
    )

    return latency <= workload.deadline

def is_service_level_allowed(workload, mode):
    """
    Defines the minimum acceptable service level
    for each workload.

    These are hard constraints and are independent
    of the optimization objective.
    """

    if workload.name in [
        "Obstacle Detection",
        "Navigation"
    ]:
        return mode != ExecutionMode.SUSPENDED

    if workload.name in [
        "Weather Analysis",
        "Video Analytics",
        "Flight Logging"
    ]:
        return True

    return True

def get_feasible_actions(
    workload: Workload,
    system: SystemState
):
    all_actions = generate_actions(workload)

    feasible_actions = []

    for location, mode in all_actions:

        if not is_service_level_allowed(workload, mode):
            continue

        if not has_enough_resources(workload, location, mode, system):
            continue

        if not network_is_feasible(
            workload,
            location,
            system
        ):
            continue

        if not meets_deadline(
            workload,
            location,
            mode,
            system
        ):
            continue

        feasible_actions.append(
            (location, mode)
        )

    return feasible_actions