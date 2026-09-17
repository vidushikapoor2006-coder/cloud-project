"""
ROBUSTNESS EVALUATION
======================

Runs the SAME three policies under the SAME randomized operating conditions
for each trial. The random seed is fixed so the experiment is reproducible.

This file does NOT change:
    - orchestrator/decision.py
    - orchestrator/utility.py
    - simulation/scenarios.py

Randomization is applied AFTER the deterministic scenario function, so each
policy sees exactly the same perturbed state for a given trial and timestep.

Outputs:
    - mean +/- standard deviation over 30 trials
    - Mission Utility
    - Feasibility Rate
    - Infeasibility Rate
    - Critical Workload Preservation Rate (CWPR)
    - Adaptations
    - Migrations
"""

import random
import statistics

from simulation.timeline import create_timeline
from simulation.records import TimeStepRecord

# Imported lazily inside run_trial to avoid a circular import when
# comparison.py imports this module for the robustness experiment.

from orchestrator.decision import select_actions_globally
from baselines.resource_aware import select_resource_aware_action

from orchestrator.feasibility import (
    get_feasible_actions,
    has_enough_resources,
    network_is_feasible,
    meets_deadline,
)

from orchestrator.resource_manager import can_allocate
from orchestrator.runtime import update_workload_state
from orchestrator.history import classify_adaptation

from models.workload import Criticality


NUM_TRIALS = 30
RANDOM_SEED = 20260909

CRITICAL_WORKLOADS = {
    "Obstacle Detection",
    "Navigation",
}

ALL_WORKLOADS_PER_STEP = 5


# ============================================================
# RANDOMIZATION
# ============================================================

def clamp(value, low, high):
    return max(low, min(high, value))


def apply_random_variation(system, rng):
    """
    Apply small stochastic perturbations to the already-selected scenario.

    The perturbations represent uncertainty in:
        - onboard / edge / cloud resource availability
        - network conditions
        - edge load
        - cloud availability
        - workload resource requirements

    The same rng state is used to create one concrete operating condition.
    The caller creates a fresh system for each policy and reapplies the SAME
    generated variation, ensuring paired/fair comparison.
    """

    # ----------------------------
    # Resource availability
    # ----------------------------

    resources = [
        system.onboard,
        system.edge_1,
        system.edge_2,
        system.cloud,
    ]

    for resource in resources:
        if not resource.available:
            continue

        # General uncertainty in current CPU/memory usage.
        cpu_factor = rng.uniform(0.90, 1.10)
        memory_factor = rng.uniform(0.90, 1.10)

        resource.cpu_used = clamp(
            resource.cpu_used * cpu_factor,
            0,
            resource.cpu_capacity,
        )

        resource.memory_used = clamp(
            resource.memory_used * memory_factor,
            0,
            resource.memory_capacity,
        )

        # Energy availability uncertainty.
        energy_factor = rng.uniform(0.90, 1.10)
        resource.energy_available = max(
            0,
            resource.energy_available * energy_factor,
        )

    # Extra edge-load uncertainty. This makes edge pressure more realistic
    # without replacing the deterministic Edge Overload scenario.
    for resource in [system.edge_1, system.edge_2]:
        if resource.available:
            cpu_extra = rng.uniform(0, 8)
            memory_extra = rng.uniform(0, 8)

            resource.cpu_used = clamp(
                resource.cpu_used + cpu_extra,
                0,
                resource.cpu_capacity,
            )

            resource.memory_used = clamp(
                resource.memory_used + memory_extra,
                0,
                resource.memory_capacity,
            )

    # ----------------------------
    # Network uncertainty
    # ----------------------------

    if system.network.connected:
        system.network.latency = max(
            0,
            system.network.latency * rng.uniform(0.90, 1.10),
        )

        system.network.bandwidth = max(
            0,
            system.network.bandwidth * rng.uniform(0.90, 1.10),
        )

        system.network.packet_loss = clamp(
            system.network.packet_loss * rng.uniform(0.90, 1.10),
            0,
            100,
        )

        # Small probability of an intermittent connection loss.
        if rng.random() < 0.05:
            system.network.connected = False
    else:
        # Do not randomly restore a scenario that explicitly represents
        # disconnection/cloud failure.
        pass

    # ----------------------------
    # Cloud availability
    # ----------------------------

    if system.cloud.available and rng.random() < 0.05:
        system.cloud.available = False

    # ----------------------------
    # Workload uncertainty
    # ----------------------------

    for workload in system.workloads:
        workload.compute_requirement = max(
            1,
            workload.compute_requirement
            * rng.uniform(0.95, 1.05),
        )

        workload.memory_requirement = max(
            1,
            workload.memory_requirement
            * rng.uniform(0.95, 1.05),
        )

        workload.energy_requirement = max(
            0.1,
            workload.energy_requirement
            * rng.uniform(0.95, 1.05),
        )

        workload.network_requirement = max(
            1,
            workload.network_requirement
            * rng.uniform(0.95, 1.05),
        )


def generate_variation(rng):
    """
    Generate random parameters once.

    This dictionary is independent of a SystemState, so it can be applied
    identically to three fresh systems.
    """

    return {
        "resource_cpu_factors": [
            rng.uniform(0.90, 1.10) for _ in range(4)
        ],
        "resource_memory_factors": [
            rng.uniform(0.90, 1.10) for _ in range(4)
        ],
        "resource_energy_factors": [
            rng.uniform(0.90, 1.10) for _ in range(4)
        ],
        "edge_cpu_extra": [
            rng.uniform(0, 8) for _ in range(2)
        ],
        "edge_memory_extra": [
            rng.uniform(0, 8) for _ in range(2)
        ],
        "network_latency_factor": rng.uniform(0.90, 1.10),
        "network_bandwidth_factor": rng.uniform(0.90, 1.10),
        "network_loss_factor": rng.uniform(0.90, 1.10),
        "connection_drop": rng.random() < 0.05,
        "cloud_failure": rng.random() < 0.05,
        "workload_compute_factors": [
            rng.uniform(0.95, 1.05) for _ in range(5)
        ],
        "workload_memory_factors": [
            rng.uniform(0.95, 1.05) for _ in range(5)
        ],
        "workload_energy_factors": [
            rng.uniform(0.95, 1.05) for _ in range(5)
        ],
        "workload_network_factors": [
            rng.uniform(0.95, 1.05) for _ in range(5)
        ],
    }


def apply_variation(system, variation):
    """Apply one pre-generated variation to a fresh SystemState."""

    resources = [
        system.onboard,
        system.edge_1,
        system.edge_2,
        system.cloud,
    ]

    for index, resource in enumerate(resources):
        if not resource.available:
            continue

        resource.cpu_used = clamp(
            resource.cpu_used
            * variation["resource_cpu_factors"][index],
            0,
            resource.cpu_capacity,
        )

        resource.memory_used = clamp(
            resource.memory_used
            * variation["resource_memory_factors"][index],
            0,
            resource.memory_capacity,
        )

        resource.energy_available = max(
            0,
            resource.energy_available
            * variation["resource_energy_factors"][index],
        )

    for index, resource in enumerate(
        [system.edge_1, system.edge_2]
    ):
        if resource.available:
            resource.cpu_used = clamp(
                resource.cpu_used
                + variation["edge_cpu_extra"][index],
                0,
                resource.cpu_capacity,
            )

            resource.memory_used = clamp(
                resource.memory_used
                + variation["edge_memory_extra"][index],
                0,
                resource.memory_capacity,
            )

    if system.network.connected:
        system.network.latency = max(
            0,
            system.network.latency
            * variation["network_latency_factor"],
        )

        system.network.bandwidth = max(
            0,
            system.network.bandwidth
            * variation["network_bandwidth_factor"],
        )

        system.network.packet_loss = clamp(
            system.network.packet_loss
            * variation["network_loss_factor"],
            0,
            100,
        )

        if variation["connection_drop"]:
            system.network.connected = False

    if system.cloud.available and variation["cloud_failure"]:
        system.cloud.available = False

    for index, workload in enumerate(system.workloads):
        workload.compute_requirement = max(
            1,
            workload.compute_requirement
            * variation["workload_compute_factors"][index],
        )

        workload.memory_requirement = max(
            1,
            workload.memory_requirement
            * variation["workload_memory_factors"][index],
        )

        workload.energy_requirement = max(
            0.1,
            workload.energy_requirement
            * variation["workload_energy_factors"][index],
        )

        workload.network_requirement = max(
            1,
            workload.network_requirement
            * variation["workload_network_factors"][index],
        )


# ============================================================
# POLICY STEPS WITH CRITICAL-WORKLOAD TRACKING
# ============================================================

def run_static_step_with_cwpr(system):
    # Use the exact Static baseline implementation from comparison.py.
    from comparison import run_static_step

    result = run_static_step(system)
    decisions = result["decisions"]

    preserved = 0

    for decision in decisions:
        if decision["workload"] not in CRITICAL_WORKLOADS:
            continue

        workload = next(
            w for w in system.workloads
            if w.name == decision["workload"]
        )

        from baselines.static_baseline import STATIC_ACTIONS

        location, mode = STATIC_ACTIONS[decision["workload"]]

        feasible = (
            has_enough_resources(
                workload, location, mode, system
            )
            and network_is_feasible(
                workload, location, system
            )
            and meets_deadline(
                workload, location, mode, system
            )
        )

        if feasible:
            preserved += 1

    normalized_result = {
        "utility": result["mission_utility"],
        "completed": result["workloads_completed"],
        "infeasible": result["workloads_infeasible"],
        "adaptations": result.get("adaptations", 0),
        "migrations": result.get("migrations", 0),
        "degradations": result.get("degradations", 0),
        "fallbacks": result.get("fallbacks", 0),
        "suspensions": result.get("suspensions", 0),
        "decisions": result.get("decisions", []),
    }

    return normalized_result, preserved


def run_resource_aware_step_with_cwpr(system):
    allocations = {}

    total_utility = 0
    feasible_count = 0
    infeasible_count = 0

    adaptations = 0
    migrations = 0
    degradations = 0
    fallbacks = 0
    suspensions = 0

    critical_preserved = 0

    workloads = sorted(
        system.workloads,
        key=lambda w: w.criticality.value,
        reverse=True,
    )

    for workload in workloads:

        old_location = workload.current_location
        old_mode = workload.current_mode

        action = select_resource_aware_action(
            workload,
            system,
            allocations,
        )

        if action is None:
            infeasible_count += 1
            continue

        location, mode = action

        update_workload_state(
            workload,
            location,
            mode,
        )

        feasible_count += 1

        utility = __import__(
            "orchestrator.utility",
            fromlist=["calculate_utility"],
        ).calculate_utility(
            workload,
            mode,
            system.mission.phase,
        )

        total_utility += utility

        if workload.name in CRITICAL_WORKLOADS:
            critical_preserved += 1

        adapted = (
            old_location != location
            or old_mode != mode
        )

        if adapted:
            adaptations += 1

        adaptation_type = classify_adaptation(
            old_location.value,
            old_mode.value,
            location.value,
            mode.value,
        )

        if "Migration" in adaptation_type:
            migrations += 1

        if adaptation_type == "Degradation":
            degradations += 1

        if adaptation_type == "Fallback":
            fallbacks += 1

        if adaptation_type == "Suspension":
            suspensions += 1

    return {
        "utility": total_utility,
        "completed": feasible_count,
        "infeasible": infeasible_count,
        "adaptations": adaptations,
        "migrations": migrations,
        "degradations": degradations,
        "fallbacks": fallbacks,
        "suspensions": suspensions,
        "decisions": [],
    }, critical_preserved


def run_proposed_step_with_cwpr(system):
    decisions = select_actions_globally(system)

    total_utility = 0
    completed = 0
    infeasible = 0

    adaptations = 0
    migrations = 0
    degradations = 0
    fallbacks = 0
    suspensions = 0

    critical_preserved = 0

    for decision in decisions:

        if decision["location"] is None:
            infeasible += 1
            continue

        completed += 1

        workload = next(
            (
                w for w in system.workloads
                if w.name == decision["workload"]
            ),
            None,
        )

        if workload is not None:
            total_utility += __import__(
                "orchestrator.utility",
                fromlist=["calculate_utility"],
            ).calculate_utility(
                workload,
                decision["mode"],
                system.mission.phase,
            )

        if decision["workload"] in CRITICAL_WORKLOADS:
            critical_preserved += 1

        if decision["adapted"]:

            adaptations += 1

            adaptation_type = decision.get(
                "adaptation_type",
                "",
            )

            if "Migration" in adaptation_type:
                migrations += 1

            if "Degradation" in adaptation_type:
                degradations += 1

            if "Fallback" in adaptation_type:
                fallbacks += 1

            if "Suspension" in adaptation_type:
                suspensions += 1

    return {
        "utility": total_utility,
        "completed": completed,
        "infeasible": infeasible,
        "adaptations": adaptations,
        "migrations": migrations,
        "degradations": degradations,
        "fallbacks": fallbacks,
        "suspensions": suspensions,
        "decisions": decisions,
    }, critical_preserved


# ============================================================
# ONE RANDOMIZED TRIAL
# ============================================================

def run_trial(trial_number, variation_seed):
    """
    Run one complete 80-step experiment.

    Every policy receives the exact same random variation at every
    timestep. Policies themselves are still run on independent fresh
    SystemState objects.
    """

    # comparison.py imports this module, so these imports must happen only
    # after comparison.py has finished initializing.
    from comparison import (
        create_system,
        SCENARIO_FUNCTIONS,
    )

    rng = random.Random(variation_seed)

    policy_names = [
        "Static",
        "Resource-Aware",
        "Proposed",
    ]

    trial_results = {}

    # Pre-generate all variations once so the three policies are paired.
    timeline = create_timeline()

    variations = [
        generate_variation(rng)
        for _ in timeline
    ]

    for policy_name in policy_names:

        system = create_system()

        records = []

        total_critical_preserved = 0
        total_critical_opportunities = (
            len(CRITICAL_WORKLOADS) * len(timeline)
        )

        for step, variation in zip(timeline, variations):

            scenario_function = SCENARIO_FUNCTIONS[
                step.scenario
            ]

            # Apply deterministic scenario first.
            scenario_function(system)

            # Apply the SAME stochastic variation used by all policies.
            apply_variation(system, variation)

            if policy_name == "Static":
                result, critical_preserved = (
                    run_static_step_with_cwpr(system)
                )

            elif policy_name == "Resource-Aware":
                result, critical_preserved = (
                    run_resource_aware_step_with_cwpr(system)
                )

            else:
                result, critical_preserved = (
                    run_proposed_step_with_cwpr(system)
                )

            total_critical_preserved += critical_preserved

            records.append(
                TimeStepRecord(
                    time=step.time,
                    scenario=step.scenario,
                    mission_utility=result["utility"],
                    workloads_completed=result["completed"],
                    workloads_infeasible=result["infeasible"],
                    adaptations=result.get("adaptations", 0),
                    migrations=result.get("migrations", 0),
                    degradations=result.get("degradations", 0),
                    fallbacks=result.get("fallbacks", 0),
                    suspensions=result.get("suspensions", 0),
                    decisions=result.get("decisions", []),
                )
            )

        total_steps = len(records)
        total_workload_assignments = (
            total_steps * ALL_WORKLOADS_PER_STEP
        )

        total_utility = sum(
            r.mission_utility for r in records
        )

        total_completed = sum(
            r.workloads_completed for r in records
        )

        total_infeasible = sum(
            r.workloads_infeasible for r in records
        )

        total_adaptations = sum(
            r.adaptations for r in records
        )

        total_migrations = sum(
            r.migrations for r in records
        )

        trial_results[policy_name] = {
            "utility": total_utility,
            "feasibility_rate": (
                total_completed
                / total_workload_assignments
                * 100
            ),
            "infeasibility_rate": (
                total_infeasible
                / total_workload_assignments
                * 100
            ),
            "cwpr": (
                total_critical_preserved
                / total_critical_opportunities
                * 100
            ),
            "adaptations": total_adaptations,
            "migrations": total_migrations,
        }

    return trial_results


# ============================================================
# STATISTICS
# ============================================================

METRICS = [
    "utility",
    "feasibility_rate",
    "infeasibility_rate",
    "cwpr",
    "adaptations",
    "migrations",
]


def mean_std(values):
    if len(values) == 1:
        return values[0], 0.0

    return (
        statistics.mean(values),
        statistics.stdev(values),
    )


def run_robustness_evaluation(
    num_trials=NUM_TRIALS,
    seed=RANDOM_SEED,
):
    print()
    print("=" * 100)
    print("             RANDOMIZED ROBUSTNESS EVALUATION")
    print("=" * 100)
    print()
    print(f"Trials: {num_trials}")
    print(f"Random seed: {seed}")
    print("Same randomized conditions are used for all three policies.")
    print()

    all_trials = []

    # Each trial gets a deterministic, reproducible seed derived from the
    # master seed. This also makes individual trials independently rerunnable.
    master_rng = random.Random(seed)

    for trial in range(1, num_trials + 1):

        trial_seed = master_rng.randint(
            0,
            2**32 - 1,
        )

        results = run_trial(
            trial_number=trial,
            variation_seed=trial_seed,
        )

        all_trials.append(results)

        print(
            f"Completed trial {trial:02d}/{num_trials}"
        )

    summary = {}

    for policy_name in [
        "Static",
        "Resource-Aware",
        "Proposed",
    ]:

        summary[policy_name] = {}

        for metric in METRICS:

            values = [
                trial[policy_name][metric]
                for trial in all_trials
            ]

            mean, std = mean_std(values)

            summary[policy_name][metric] = {
                "mean": mean,
                "std": std,
                "values": values,
            }

    print()
    print("=" * 100)
    print("                 ROBUSTNESS RESULTS (MEAN +/- STD)")
    print("=" * 100)
    print()

    headers = [
        ("Mission Utility", "utility", ".2f"),
        ("Feasibility Rate (%)", "feasibility_rate", ".2f"),
        ("Infeasibility Rate (%)", "infeasibility_rate", ".2f"),
        ("Critical Workload Preservation (%)", "cwpr", ".2f"),
        ("Total Adaptations", "adaptations", ".2f"),
        ("Total Migrations", "migrations", ".2f"),
    ]

    print(
        f"{'Metric':<42}"
        f"{'Static':>22}"
        f"{'Resource-Aware':>24}"
        f"{'Proposed':>22}"
    )

    print("-" * 112)

    for label, metric, fmt in headers:

        row = [label]

        for policy in [
            "Static",
            "Resource-Aware",
            "Proposed",
        ]:
            mean = summary[policy][metric]["mean"]
            std = summary[policy][metric]["std"]

            row.append(
                f"{mean:{fmt}} +/- {std:{fmt}}"
            )

        print(
            f"{row[0]:<42}"
            f"{row[1]:>22}"
            f"{row[2]:>24}"
            f"{row[3]:>22}"
        )

    # Improvement calculations use means across the randomized trials.
    proposed_utility = summary["Proposed"]["utility"]["mean"]
    static_utility = summary["Static"]["utility"]["mean"]
    resource_utility = summary["Resource-Aware"]["utility"]["mean"]

    proposed_infeas = (
        summary["Proposed"]["infeasibility_rate"]["mean"]
    )
    static_infeas = (
        summary["Static"]["infeasibility_rate"]["mean"]
    )
    resource_infeas = (
        summary["Resource-Aware"]["infeasibility_rate"]["mean"]
    )

    print()
    print("=" * 100)
    print("                 PROPOSED POLICY IMPROVEMENT")
    print("=" * 100)
    print()

    if static_utility != 0:
        print(
            "Mean mission utility improvement vs Static: "
            f"{((proposed_utility - static_utility) / static_utility) * 100:.2f}%"
        )

    if resource_utility != 0:
        print(
            "Mean mission utility improvement vs Resource-Aware: "
            f"{((proposed_utility - resource_utility) / resource_utility) * 100:.2f}%"
        )

    if static_infeas != 0:
        print(
            "Mean infeasibility reduction vs Static: "
            f"{((static_infeas - proposed_infeas) / static_infeas) * 100:.2f}%"
        )

    if resource_infeas != 0:
        print(
            "Mean infeasibility reduction vs Resource-Aware: "
            f"{((resource_infeas - proposed_infeas) / resource_infeas) * 100:.2f}%"
        )

    print()
    print("Experiment completed.")
    print()

    return {
        "seed": seed,
        "num_trials": num_trials,
        "trial_results": all_trials,
        "summary": summary,
    }


# This module is intentionally invoked from comparison.py.
# Running comparison.py is the supported entry point for the full experiment.
