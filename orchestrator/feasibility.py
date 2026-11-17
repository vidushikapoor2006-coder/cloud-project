"""Hard feasibility constraints (Section III-D of the revised paper).

Changes in this revision (marked "REV"):
  * REV-safety: Obstacle Detection and Navigation may execute only onboard
    (Reviewer 2, comment 9).  Enforced in the action catalogue AND by an
    explicit check, so that no policy can bypass it.
  * REV-loss: packet loss inflates the expected network delay through
    retransmissions, L_net / (1 - p).  The original manuscript stated that
    packet loss produces a communication-quality cost, but the original code
    did not use packet loss for the proposed policy.
  * REV-coverage: an edge node is reachable only inside its coverage radius
    (mobility-dependent handover); unlimited when coverage_radius_km is None.
  * REV-migration-deadline (optional, config.MIGRATION_DOWNTIME_IN_DEADLINE):
    under a cold-migration assumption the migration time is added to the
    response time before the deadline check, identically for every policy.
    Disabled by default (live migration, as in the original model).
"""

import config
from models.workload import Workload, Location, ExecutionMode
from models.state import SystemState
from orchestrator.migration import is_migration, calculate_migration_cost


def generate_actions(workload: Workload):
    """Catalogue of (location, mode) actions per workload (Table III)."""

    actions = []

    if workload.name in config.SAFETY_ONBOARD_ONLY:
        # REV-safety: flight-critical functions stay on the certified
        # onboard computer.  Reduced and Fallback are onboard degraded
        # modes; Suspended is never allowed (see is_service_level_allowed).
        actions = [
            (Location.ONBOARD, ExecutionMode.FULL),
            (Location.ONBOARD, ExecutionMode.REDUCED),
            (Location.ONBOARD, ExecutionMode.FALLBACK),
        ]

    elif workload.name in ("Weather Analysis", "Flight Logging"):
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

    return actions


def is_location_allowed(workload: Workload, location: Location):
    """REV-safety: hard placement restriction for flight-critical work."""
    if workload.name in config.SAFETY_ONBOARD_ONLY:
        return location == Location.ONBOARD
    return True


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


def scaled_requirements(workload: Workload, mode: ExecutionMode):
    """(cpu, memory, energy) demand of a workload in a mode: kappa(q) * r_i."""
    k = config.MODE_SCALE[mode.value]
    return (workload.compute_requirement * k,
            workload.memory_requirement * k,
            workload.energy_requirement * k)


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

    # Suspended workload uses no execution resources
    if mode == ExecutionMode.SUSPENDED:
        return True

    compute_requirement, memory_requirement, energy_requirement = \
        scaled_requirements(workload, mode)

    if resource.cpu_available < compute_requirement:
        return False

    if resource.memory_available < memory_requirement:
        return False

    if resource.energy_available < energy_requirement:
        return False

    return True


def link_is_up(location: Location, system: SystemState):
    """Reachability of a remote location (air-ground link + edge coverage)."""
    if location == Location.ONBOARD:
        return True
    if not system.network.connected:
        return False
    if location in (Location.EDGE_1, Location.EDGE_2):
        return config.edge_in_coverage(
            location.value, system.evtol_position,
            radius_km=(float("inf") if system.coverage_radius_km is None
                       else system.coverage_radius_km))
    return True


def network_is_feasible(
    workload: Workload,
    location: Location,
    system: SystemState
):
    # Onboard execution does not require external network
    if location == Location.ONBOARD:
        return True

    # No connection / out of coverage means remote execution is impossible
    if not link_is_up(location, system):
        return False

    # Check bandwidth requirement
    if system.network.bandwidth < workload.network_requirement:
        return False

    return True


def network_latency(location: Location, system: SystemState,
                    latency_override=None, loss_override=None):
    """Expected one-way network delay to a location [ms] (Eq. (9))."""
    if location == Location.ONBOARD:
        return 0.0
    base_latency = (system.network.latency if latency_override is None
                    else latency_override)
    if location.value in config.EDGE_POSITIONS_KM:
        distance = abs(system.evtol_position
                       - config.EDGE_POSITIONS_KM[location.value])
        base_latency = base_latency + distance * config.DISTANCE_LATENCY_MS_PER_KM
    loss_pct = (system.network.packet_loss if loss_override is None
                else loss_override)
    p = min(max(loss_pct / 100.0, 0.0), 0.95)
    # REV-loss: expected number of transmissions under ARQ is 1 / (1 - p).
    return base_latency / (1.0 - p)


def estimate_latency(
    workload: Workload,
    location: Location,
    mode: ExecutionMode,
    system: SystemState
):
    """Response-time estimate T_i(a) [ms] without migration (Eq. (10))."""
    if mode == ExecutionMode.SUSPENDED:
        return 0

    compute_latency = (workload.compute_requirement
                       * config.MODE_SCALE[mode.value])

    return compute_latency + network_latency(location, system)


def migration_time_if_moved(workload, location, system):
    if not is_migration(workload, location):
        return 0.0
    return calculate_migration_cost(
        workload, workload.current_location, location, system
    )["migration_time_ms"]


def meets_deadline(
    workload: Workload,
    location: Location,
    mode: ExecutionMode,
    system: SystemState,
    include_migration: bool = True,
):
    if mode == ExecutionMode.SUSPENDED:
        return True

    latency = estimate_latency(
        workload,
        location,
        mode,
        system
    )

    if include_migration and config.MIGRATION_DOWNTIME_IN_DEADLINE:
        latency += migration_time_if_moved(workload, location, system)

    return latency <= workload.deadline


def is_service_level_allowed(workload, mode):
    """
    Defines the minimum acceptable service level
    for each workload.

    These are hard constraints and are independent
    of the optimization objective.
    """

    if workload.name in config.SAFETY_ONBOARD_ONLY:
        return mode != ExecutionMode.SUSPENDED

    return True


def is_action_feasible(workload, location, mode, system,
                       include_migration=True):
    return (
        is_location_allowed(workload, location)
        and is_service_level_allowed(workload, mode)
        and has_enough_resources(workload, location, mode, system)
        and network_is_feasible(workload, location, system)
        and meets_deadline(workload, location, mode, system,
                           include_migration=include_migration)
    )


def get_feasible_actions(
    workload: Workload,
    system: SystemState,
    include_migration: bool = True,
):
    return [
        (location, mode)
        for location, mode in generate_actions(workload)
        if is_action_feasible(workload, location, mode, system,
                              include_migration=include_migration)
    ]
