from itertools import product

from models.workload import Criticality, ExecutionMode

from orchestrator.feasibility import get_feasible_actions
from orchestrator.utility import calculate_score, calculate_utility, QUALITY_FACTOR
from orchestrator.resource_manager import can_allocate, allocate
from orchestrator.runtime import update_workload_state
from orchestrator.history import classify_adaptation


# Migration model parameters for analytical migration overhead.
MIGRATION_BANDWIDTH_MBPS = 50.0
EDGE_TO_EDGE_LATENCY_MS = 20.0
MIGRATION_OVERHEAD_MS = 5.0
MIGRATION_COST_SCALE = 20.0


def calculate_migration_cost(workload, old_location, new_location, system):
    """Return analytical migration time and normalized migration cost.

    A location change is treated as a soft orchestration cost, not a hard
    feasibility constraint. The model charges for transferring the workload
    state plus network/coordination overhead. Initial placement is not charged.
    """
    # A workload with no previous runtime placement is an initial placement,
    # not a migration. Runtime code sets previous_location after the first
    # committed decision.
    if (
        old_location is None
        or old_location == new_location
        or getattr(workload, "previous_location", None) is None
    ):
        return {"migration_time_ms": 0.0, "migration_cost": 0.0}

    state_size_mb = max(float(getattr(workload, "state_size_mb", 1.0)), 0.0)
    effective_bandwidth = max(
        min(MIGRATION_BANDWIDTH_MBPS, float(system.network.bandwidth)),
        1e-6
    )
    transfer_time_ms = (state_size_mb / effective_bandwidth) * 1000.0

    if old_location.value.startswith("Edge_") and new_location.value.startswith("Edge_"):
        path_latency_ms = EDGE_TO_EDGE_LATENCY_MS
    else:
        path_latency_ms = float(system.network.latency)

    migration_time_ms = (
        transfer_time_ms
        + path_latency_ms
        + MIGRATION_OVERHEAD_MS
    )

    migration_cost = (
        migration_time_ms / max(workload.deadline, 1.0)
    ) * MIGRATION_COST_SCALE

    return {
        "migration_time_ms": migration_time_ms,
        "migration_cost": migration_cost,
    }


def _migration_allowed(workload, old_location, new_location, candidate_score,
                       current_score, system):
    """Permit migration when it is initial placement, recovery, or beneficial."""
    if (
        old_location is None
        or old_location == new_location
        or getattr(workload, "previous_location", None) is None
    ):
        return True

    migration = calculate_migration_cost(
        workload, old_location, new_location, system
    )

    # If the current action is not feasible, migration is a recovery action.
    if current_score is None:
        return True

    operating_benefit = candidate_score - current_score
    return operating_benefit > migration["migration_cost"]


def _evaluate_action(workload, location, mode, system, allocations):
    """Evaluate an action including migration overhead and stability cost."""
    if not can_allocate(
        workload, location, mode, system, allocations
    ):
        return None

    result = calculate_score(
        workload, location, mode, system
    )

    old_location = workload.current_location
    migration = calculate_migration_cost(
        workload, old_location, location, system
    )

    current_result = None
    if old_location is not None:
        current_mode = workload.current_mode
        # The current action is a valid reference only when it satisfies the
        # same hard feasibility rules (resource, connectivity/bandwidth and
        # deadline) used for candidate actions. If it is no longer feasible,
        # a location change is treated as recovery and migration is allowed.
        current_action = (old_location, current_mode)
        if (
            current_action in get_feasible_actions(workload, system)
            and can_allocate(workload, old_location, current_mode, system, {})
        ):
            current_result = calculate_score(
                workload, old_location, current_mode, system
            )["score"]

    # A change is worthwhile only when the operating-score improvement
    # exceeds the migration overhead. If the current placement is infeasible,
    # migration is allowed as recovery.
    if not _migration_allowed(
        workload, old_location, location, result["score"],
        current_result, system
    ):
        return None

    result["migration_time_ms"] = migration["migration_time_ms"]
    result["migration_cost"] = migration["migration_cost"]
    result["base_score"] = result["score"]
    result["score"] -= migration["migration_cost"]
    result["migration_benefit"] = (
        None if current_result is None
        else result["base_score"] - current_result
    )

    return result


def _critical_workload(workload):
    """Mission-critical workloads are explicitly marked VERY_HIGH."""
    return workload.criticality == Criticality.VERY_HIGH


def _joint_allocate(critical_workloads, action_combination, system):
    """Check whether a complete critical-workload action combination fits."""
    allocations = {}

    for workload, (location, mode) in zip(
        critical_workloads,
        action_combination
    ):
        if not can_allocate(
            workload,
            location,
            mode,
            system,
            allocations
        ):
            return None

        allocate(
            workload,
            location,
            mode,
            allocations
        )

    return allocations


def _select_critical_actions(critical_workloads, system):
    """
    Jointly select actions for mission-critical workloads.

    The objective is lexicographic:
      1. Preserve critical service (never intentionally suspend a critical workload).
      2. Maximize aggregate mission utility of critical workloads.
      3. Maximize the minimum critical-workload quality.
      4. Minimize the aggregate orchestration cost.

    The critical action space is intentionally small in this prototype, so
    exhaustive enumeration is used instead of a heavyweight optimizer.
    """
    action_lists = []

    for workload in critical_workloads:
        feasible = [
            action
            for action in get_feasible_actions(workload, system)
            if action[1] != ExecutionMode.SUSPENDED
        ]

        if not feasible:
            action_lists.append([])
        else:
            action_lists.append(feasible)

    if any(not actions for actions in action_lists):
        return None, {}

    best = None

    for combination in product(*action_lists):
        allocations = _joint_allocate(
            critical_workloads,
            combination,
            system
        )

        if allocations is None:
            continue

        total_utility = 0.0
        quality_values = []
        total_cost = 0.0
        results = []

        for workload, (location, mode) in zip(
            critical_workloads,
            combination
        ):
            result = calculate_score(
                workload,
                location,
                mode,
                system
            )

            old_location = workload.current_location
            migration = calculate_migration_cost(
                workload, old_location, location, system
            )

            current_result = None
            current_action = (old_location, workload.current_mode)
            if (
                old_location is not None
                and current_action in get_feasible_actions(workload, system)
                and can_allocate(
                    workload, old_location, workload.current_mode, system, {}
                )
            ):
                current_result = calculate_score(
                    workload, old_location, workload.current_mode, system
                )["score"]

            if not _migration_allowed(
                workload, old_location, location, result["score"],
                current_result, system
            ):
                results = []
                break

            result["migration_time_ms"] = migration["migration_time_ms"]
            result["migration_cost"] = migration["migration_cost"]
            result["base_score"] = result["score"]
            result["score"] -= migration["migration_cost"]
            result["migration_benefit"] = (
                None if current_result is None
                else result["base_score"] - current_result
            )

            utility = calculate_utility(
                workload,
                mode,
                system.mission.phase
            )

            total_utility += utility
            quality_values.append(
                QUALITY_FACTOR[workload.name][mode]
            )
            total_cost += (
                result["latency_cost"]
                + result["energy_cost"]
                + result["resource_cost"]
            )
            results.append(result)

        if not results:
            continue

        min_quality = min(quality_values)

        # Higher utility first; then protect the weakest critical workload;
        # finally prefer lower cost. Tuple is ordered for max().
        candidate_key = (
            total_utility,
            min_quality,
            -total_cost
        )

        if best is None or candidate_key > best["key"]:
            best = {
                "key": candidate_key,
                "combination": combination,
                "allocations": allocations,
                "results": results
            }

    if best is None:
        return None, {}

    return best, best["allocations"]


def _commit_decision(workload, location, mode, result, allocations, decisions):
    """Apply a selected action and append a standard decision record."""
    old_location = workload.current_location
    old_mode = workload.current_mode

    update_workload_state(
        workload,
        location,
        mode
    )

    allocate(
        workload,
        location,
        mode,
        allocations
    )

    adapted = (
        old_location != location
        or old_mode != mode
    )

    adaptation_type = classify_adaptation(
        old_location.value,
        old_mode.value,
        location.value,
        mode.value
    )

    decisions.append({
        "workload": workload.name,
        "location": location,
        "mode": mode,
        "score": result["score"],
        "details": result,
        "adaptation_type": adaptation_type,
        "adapted": adapted
    })


def _append_infeasible(workload, decisions):
    decisions.append({
        "workload": workload.name,
        "location": None,
        "mode": None,
        "score": None,
        "adapted": False
    })


def select_actions_globally(system):
    """
    Mission-aware adaptive orchestration policy.

    Unlike the old purely sequential greedy policy, mission-critical
    workloads are selected jointly first. This prevents lower-priority
    workloads from consuming resources that are needed to preserve critical
    functionality.

    After critical workloads are protected, remaining workloads are selected
    using the existing utility/cost scoring mechanism.
    """
    allocations = {}
    decisions = []

    critical_workloads = [
        workload
        for workload in system.workloads
        if _critical_workload(workload)
    ]

    noncritical_workloads = [
        workload
        for workload in system.workloads
        if not _critical_workload(workload)
    ]

    # ------------------------------------------------------------
    # PHASE 1: Joint protection of mission-critical workloads
    # ------------------------------------------------------------
    critical_selection, critical_allocations = _select_critical_actions(
        critical_workloads,
        system
    )

    if critical_selection is not None:
        # Recreate the critical allocation map by committing each action.
        for workload, (location, mode), result in zip(
            critical_workloads,
            critical_selection["combination"],
            critical_selection["results"]
        ):
            _commit_decision(
                workload,
                location,
                mode,
                result,
                allocations,
                decisions
            )
    else:
        # If no joint feasible critical combination exists, fall back to the
        # old criticality-ordered greedy mechanism. This represents a true
        # physical/resource infeasibility rather than sacrificing a critical
        # workload because a lower-priority workload was allocated first.
        for workload in sorted(
            critical_workloads,
            key=lambda w: w.criticality.value,
            reverse=True
        ):
            feasible_actions = get_feasible_actions(
                workload,
                system
            )

            candidates = []

            for location, mode in feasible_actions:
                if mode == ExecutionMode.SUSPENDED:
                    continue

                result = _evaluate_action(
                    workload,
                    location,
                    mode,
                    system,
                    allocations
                )

                if result is not None:
                    candidates.append((location, mode, result))

            if not candidates:
                _append_infeasible(workload, decisions)
                continue

            best = max(
                candidates,
                key=lambda x: x[2]["score"]
            )

            _commit_decision(
                workload,
                best[0],
                best[1],
                best[2],
                allocations,
                decisions
            )

    # ------------------------------------------------------------
    # PHASE 2: Allocate remaining resources to non-critical work
    # ------------------------------------------------------------
    for workload in sorted(
        noncritical_workloads,
        key=lambda w: w.criticality.value,
        reverse=True
    ):
        feasible_actions = get_feasible_actions(
            workload,
            system
        )

        candidates = []

        for location, mode in feasible_actions:
            result = _evaluate_action(
                workload,
                location,
                mode,
                system,
                allocations
            )

            if result is None:
                continue

            candidates.append((location, mode, result))

        if not candidates:
            _append_infeasible(workload, decisions)
            continue

        # Phase 2 is still mission-aware: first maximize mission utility
        # (service quality weighted by the current mission phase). Only when
        # two actions provide the same utility do we use the orchestration
        # score as the efficiency tie-breaker.
        #
        # This prevents the policy from selecting an unnecessarily degraded
        # service merely because it has a lower resource/latency cost.
        best = max(
            candidates,
            key=lambda x: (
                calculate_utility(
                    workload,
                    x[1],
                    system.mission.phase
                ),
                x[2]["score"]
            )
        )

        _commit_decision(
            workload,
            best[0],
            best[1],
            best[2],
            allocations,
            decisions
        )

    return decisions
