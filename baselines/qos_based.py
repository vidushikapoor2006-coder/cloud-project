from models.workload import ExecutionMode
from orchestrator.feasibility import get_feasible_actions
from orchestrator.resource_manager import can_allocate, allocate
from orchestrator.utility import calculate_latency_cost


ALPHA_LATENCY = 0.50
BETA_BANDWIDTH = 0.25
GAMMA_PACKET_LOSS = 0.25


def calculate_qos_score(
    workload,
    location,
    mode,
    system
):
    """
    Lower score is better.

    QoS-Based baseline considers:
    - latency
    - bandwidth
    - packet loss

    It does NOT consider:
    - mission utility
    - mission phase
    - workload criticality
    - resource efficiency
    """

    latency_cost = calculate_latency_cost(
        workload,
        location,
        mode,
        system
    )

    latency_normalized = latency_cost / max(
        workload.deadline * 20,
        1
    )

    bandwidth = system.network.bandwidth

    if bandwidth >= workload.network_requirement:
        bandwidth_penalty = 0.0
    else:
        bandwidth_penalty = (
            workload.network_requirement - bandwidth
        ) / max(
            workload.network_requirement,
            1
        )

    packet_loss_penalty = (
        system.network.packet_loss / 100
    )

    score = (
        ALPHA_LATENCY * latency_normalized
        + BETA_BANDWIDTH * bandwidth_penalty
        + GAMMA_PACKET_LOSS * packet_loss_penalty
    )

    return score


def select_qos_based_action(
    workload,
    system,
    allocations
):
    """
    Select the highest feasible service level.

    Within that service level, choose the
    action with the best QoS score.
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

        score = calculate_qos_score(
            workload,
            location,
            mode,
            system
        )

        candidates.append(
            (
                score,
                location,
                mode
            )
        )

    if not candidates:
        return None

    # QoS baseline: choose the action with the best QoS
    # among all feasible NON-SUSPENDED actions.
    #
    # This baseline does not use mission utility, mission phase,
    # or workload criticality. It may therefore sacrifice service
    # quality when doing so improves network QoS.
    non_suspended = [
        candidate
        for candidate in candidates
        if candidate[2] != ExecutionMode.SUSPENDED
    ]

    if non_suspended:
        best_score, best_location, best_mode = min(
            non_suspended,
            key=lambda x: x[0]
        )

        allocate(
            workload,
            best_location,
            best_mode,
            allocations
        )

        return best_location, best_mode

    # Suspend only when no executable action is feasible.
    suspended_candidates = [
        candidate
        for candidate in candidates
        if candidate[2] == ExecutionMode.SUSPENDED
    ]

    if suspended_candidates:
        best_score, best_location, best_mode = min(
            suspended_candidates,
            key=lambda x: x[0]
        )

        allocate(
            workload,
            best_location,
            best_mode,
            allocations
        )

        return best_location, best_mode

    return None