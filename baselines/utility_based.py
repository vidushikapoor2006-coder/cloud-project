from models.workload import ExecutionMode
from orchestrator.feasibility import get_feasible_actions
from orchestrator.resource_manager import can_allocate, allocate
from orchestrator.utility import (
    calculate_utility,
    calculate_latency_cost
)


def select_utility_based_action(
    workload,
    system,
    allocations
):
    """
    Utility-Based baseline.

    Selects the feasible action that maximizes
    mission utility.

    It does NOT use the proposed policy's
    joint critical-workload protection or
    combined utility/resource optimization.
    """

    feasible_actions = get_feasible_actions(
        workload,
        system
    )

    candidates = []

    for location, mode in feasible_actions:

        if not can_allocate(
            workload,
            location,
            mode,
            system,
            allocations
        ):
            continue

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

        candidates.append(
            (
                utility,
                -latency_cost,
                location,
                mode
            )
        )

    if not candidates:
        return None

    # Highest mission utility first.
    # If utility is equal, prefer lower latency.
    best = max(
        candidates,
        key=lambda x: (
            x[0],
            x[1]
        )
    )

    utility, negative_latency, location, mode = best

    allocate(
        workload,
        location,
        mode,
        allocations
    )

    return location, mode