from collections import defaultdict
from statistics import mean


POLICIES = [
    "Static",
    "Resource-Aware",
    "Proposed"
]


# ============================================================
# BASIC AGGREGATION FUNCTIONS
# ============================================================

def calculate_total(records, attribute):
    return sum(
        getattr(record, attribute, 0)
        for record in records
    )


def calculate_average(records, attribute):
    values = [
        getattr(record, attribute, 0)
        for record in records
    ]

    if not values:
        return 0.0

    return mean(values)


# ============================================================
# FEASIBILITY METRICS
# ============================================================

def calculate_feasibility_rate(records):

    total_completed = calculate_total(
        records,
        "workloads_completed"
    )

    total_infeasible = calculate_total(
        records,
        "workloads_infeasible"
    )

    total_assignments = (
        total_completed +
        total_infeasible
    )

    if total_assignments == 0:
        return 0.0

    return (
        total_completed /
        total_assignments
    ) * 100


def calculate_infeasibility_rate(records):

    total_completed = calculate_total(
        records,
        "workloads_completed"
    )

    total_infeasible = calculate_total(
        records,
        "workloads_infeasible"
    )

    total_assignments = (
        total_completed +
        total_infeasible
    )

    if total_assignments == 0:
        return 0.0

    return (
        total_infeasible /
        total_assignments
    ) * 100


# ============================================================
# ADAPTATION METRICS
# ============================================================

def calculate_adaptation_rate(records):

    total_adaptations = calculate_total(
        records,
        "adaptations"
    )

    if not records:
        return 0.0

    return total_adaptations / len(records)


# ============================================================
# CRITICAL WORKLOAD PRESERVATION
# ============================================================

def calculate_critical_workload_preservation(records):
    """
    Calculate Critical Workload Preservation Rate (CWPR).

    Critical workloads:
        - Obstacle Detection
        - Navigation

    Operational states:
        - Full
        - Reduced
        - Fallback

    Non-preserved states:
        - Suspended
        - Infeasible
        - Missing decision

    Formula:

        CWPR =
        (preserved critical workload decisions /
         total critical workload decisions) * 100
    """

    critical_workloads = {
        "Obstacle Detection",
        "Navigation"
    }

    total_critical_decisions = 0
    preserved_critical_decisions = 0

    for record in records:

        # TimeStepRecord stores workload decisions
        # in record.decisions, NOT record.results.
        decisions = getattr(
            record,
            "decisions",
            []
        )

        for decision in decisions:

            workload_name = decision.get(
                "workload"
            )

            if workload_name not in critical_workloads:
                continue

            total_critical_decisions += 1

            location = decision.get(
                "location"
            )

            mode = decision.get(
                "mode"
            )

            # Enum values may appear as:
            # ExecutionMode.FULL
            # or "Full"
            #
            # Convert enum values to their string value
            # when necessary.

            if hasattr(mode, "value"):
                mode = mode.value

            if hasattr(location, "value"):
                location = location.value

            # A valid operational decision must have
            # both a location and a supported mode.

            if (
                location is not None
                and mode in [
                    "Full",
                    "Reduced",
                    "Fallback"
                ]
            ):
                preserved_critical_decisions += 1

    if total_critical_decisions == 0:
        return 0.0

    return (
        preserved_critical_decisions /
        total_critical_decisions
    ) * 100


# ============================================================
# SCENARIO-LEVEL METRICS
# ============================================================

def calculate_scenario_metrics(records):

    scenario_data = defaultdict(list)

    for record in records:
        scenario_data[
            record.scenario
        ].append(record)

    results = {}

    for scenario, scenario_records in scenario_data.items():

        total_utility = calculate_total(
            scenario_records,
            "mission_utility"
        )

        total_completed = calculate_total(
            scenario_records,
            "workloads_completed"
        )

        total_infeasible = calculate_total(
            scenario_records,
            "workloads_infeasible"
        )

        total_assignments = (
            total_completed +
            total_infeasible
        )

        results[scenario] = {

            "utility": total_utility,

            "average_utility": (
                total_utility /
                len(scenario_records)
            ),

            "completed": total_completed,

            "infeasible": total_infeasible,

            "feasibility_rate": (
                total_completed /
                total_assignments
                * 100
                if total_assignments > 0
                else 0.0
            ),

            "adaptations": calculate_total(
                scenario_records,
                "adaptations"
            ),

            "migrations": calculate_total(
                scenario_records,
                "migrations"
            ),

            "degradations": calculate_total(
                scenario_records,
                "degradations"
            ),

            "fallbacks": calculate_total(
                scenario_records,
                "fallbacks"
            ),

            "suspensions": calculate_total(
                scenario_records,
                "suspensions"
            )
        }

    return results


# ============================================================
# COMPLETE POLICY EVALUATION
# ============================================================

def evaluate_policy(records):

    return {

        "total_utility": calculate_total(
            records,
            "mission_utility"
        ),

        "total_completed": calculate_total(
            records,
            "workloads_completed"
        ),

        "total_infeasible": calculate_total(
            records,
            "workloads_infeasible"
        ),

        "feasibility_rate": calculate_feasibility_rate(
            records
        ),

        "infeasibility_rate": calculate_infeasibility_rate(
            records
        ),

        "total_adaptations": calculate_total(
            records,
            "adaptations"
        ),

        "total_migrations": calculate_total(
            records,
            "migrations"
        ),

        "total_degradations": calculate_total(
            records,
            "degradations"
        ),

        "total_fallbacks": calculate_total(
            records,
            "fallbacks"
        ),

        "total_suspensions": calculate_total(
            records,
            "suspensions"
        ),

        "average_adaptations_per_step":
            calculate_adaptation_rate(
                records
            ),

        "critical_workload_preservation_rate":
            calculate_critical_workload_preservation(
                records
            )
    }


# ============================================================
# OVERALL EVALUATION PRINTING
# ============================================================

def print_evaluation(
    static_records,
    resource_records,
    proposed_records
):

    all_results = {

        "Static": evaluate_policy(
            static_records
        ),

        "Resource-Aware": evaluate_policy(
            resource_records
        ),

        "Proposed": evaluate_policy(
            proposed_records
        )
    }

    print()
    print("=" * 110)
    print("                         RESEARCH EVALUATION")
    print("=" * 110)

    print()

    print(
        f"{'Metric':<40}"
        f"{'Static':>18}"
        f"{'Resource-Aware':>20}"
        f"{'Proposed':>18}"
    )

    print("-" * 110)

    metrics = [

        (
            "Total Mission Utility",
            "total_utility",
            ".2f"
        ),

        (
            "Feasibility Rate (%)",
            "feasibility_rate",
            ".2f"
        ),

        (
            "Infeasibility Rate (%)",
            "infeasibility_rate",
            ".2f"
        ),

        (
            "Critical Workload Preservation (%)",
            "critical_workload_preservation_rate",
            ".2f"
        ),

        (
            "Total Adaptations",
            "total_adaptations",
            "d"
        ),

        (
            "Total Migrations",
            "total_migrations",
            "d"
        ),

        (
            "Total Degradations",
            "total_degradations",
            "d"
        ),

        (
            "Total Fallbacks",
            "total_fallbacks",
            "d"
        ),

        (
            "Total Suspensions",
            "total_suspensions",
            "d"
        ),

        (
            "Avg Adaptations / Step",
            "average_adaptations_per_step",
            ".2f"
        )
    ]

    for label, key, fmt in metrics:

        static_value = all_results[
            "Static"
        ][key]

        resource_value = all_results[
            "Resource-Aware"
        ][key]

        proposed_value = all_results[
            "Proposed"
        ][key]

        print(
            f"{label:<40}"
            f"{format(static_value, fmt):>18}"
            f"{format(resource_value, fmt):>20}"
            f"{format(proposed_value, fmt):>18}"
        )

    print()

    # ========================================================
    # PROPOSED IMPROVEMENT OVER BASELINES
    # ========================================================

    print("=" * 110)
    print("                    PROPOSED IMPROVEMENT OVER BASELINES")
    print("=" * 110)

    static_utility = all_results[
        "Static"
    ]["total_utility"]

    resource_utility = all_results[
        "Resource-Aware"
    ]["total_utility"]

    proposed_utility = all_results[
        "Proposed"
    ]["total_utility"]

    if static_utility != 0:

        static_improvement = (
            (
                proposed_utility -
                static_utility
            )
            / static_utility
        ) * 100

    else:

        static_improvement = 0.0

    if resource_utility != 0:

        resource_improvement = (
            (
                proposed_utility -
                resource_utility
            )
            / resource_utility
        ) * 100

    else:

        resource_improvement = 0.0

    static_infeasible = all_results[
        "Static"
    ]["total_infeasible"]

    resource_infeasible = all_results[
        "Resource-Aware"
    ]["total_infeasible"]

    proposed_infeasible = all_results[
        "Proposed"
    ]["total_infeasible"]

    if static_infeasible != 0:

        static_reduction = (
            (
                static_infeasible -
                proposed_infeasible
            )
            / static_infeasible
        ) * 100

    else:

        static_reduction = 0.0

    if resource_infeasible != 0:

        resource_reduction = (
            (
                resource_infeasible -
                proposed_infeasible
            )
            / resource_infeasible
        ) * 100

    else:

        resource_reduction = 0.0

    print(
        f"Mission utility improvement vs Static: "
        f"{static_improvement:.2f}%"
    )

    print(
        f"Mission utility improvement vs Resource-Aware: "
        f"{resource_improvement:.2f}%"
    )

    print(
        f"Infeasibility reduction vs Static: "
        f"{static_reduction:.2f}%"
    )

    print(
        f"Infeasibility reduction vs Resource-Aware: "
        f"{resource_reduction:.2f}%"
    )

    print()


# ============================================================
# SCENARIO FEASIBILITY EVALUATION
# ============================================================

def print_scenario_evaluation(
    static_records,
    resource_records,
    proposed_records
):

    static_data = calculate_scenario_metrics(
        static_records
    )

    resource_data = calculate_scenario_metrics(
        resource_records
    )

    proposed_data = calculate_scenario_metrics(
        proposed_records
    )

    scenario_order = [

        "Normal",

        "Network Degradation",

        "Edge Overload",

        "Cloud Failure",

        "Resource Pressure",

        "Emergency Mission",

        "Severe Degradation",

        "Recovery"
    ]

    print()
    print("=" * 110)
    print("                    SCENARIO FEASIBILITY EVALUATION")
    print("=" * 110)

    print()

    print(
        f"{'Scenario':<25}"
        f"{'Static':>18}"
        f"{'Resource-Aware':>20}"
        f"{'Proposed':>18}"
    )

    print("-" * 110)

    for scenario in scenario_order:

        if scenario not in static_data:
            continue

        print(
            f"{scenario:<25}"
            f"{static_data[scenario]['feasibility_rate']:>17.2f}%"
            f"{resource_data[scenario]['feasibility_rate']:>19.2f}%"
            f"{proposed_data[scenario]['feasibility_rate']:>17.2f}%"
        )


# ============================================================
# SCENARIO MISSION UTILITY EVALUATION
# ============================================================

def print_scenario_utility_evaluation(
    static_records,
    resource_records,
    proposed_records
):

    static_data = calculate_scenario_metrics(
        static_records
    )

    resource_data = calculate_scenario_metrics(
        resource_records
    )

    proposed_data = calculate_scenario_metrics(
        proposed_records
    )

    scenario_order = [

        "Normal",

        "Network Degradation",

        "Edge Overload",

        "Cloud Failure",

        "Resource Pressure",

        "Emergency Mission",

        "Severe Degradation",

        "Recovery"
    ]

    print()
    print("=" * 110)
    print("                    SCENARIO MISSION UTILITY")
    print("=" * 110)

    print()

    print(
        f"{'Scenario':<25}"
        f"{'Static':>18}"
        f"{'Resource-Aware':>20}"
        f"{'Proposed':>18}"
    )

    print("-" * 110)

    for scenario in scenario_order:

        if scenario not in static_data:
            continue

        print(
            f"{scenario:<25}"
            f"{static_data[scenario]['utility']:>18.2f}"
            f"{resource_data[scenario]['utility']:>20.2f}"
            f"{proposed_data[scenario]['utility']:>18.2f}"
        )


# ============================================================
# MAIN EVALUATION ENTRY POINT
# ============================================================

def run_evaluation(
    static_records,
    resource_records,
    proposed_records
):

    print_evaluation(
        static_records,
        resource_records,
        proposed_records
    )

    print_scenario_evaluation(
        static_records,
        resource_records,
        proposed_records
    )

    print_scenario_utility_evaluation(
        static_records,
        resource_records,
        proposed_records
    )