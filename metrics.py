from dataclasses import dataclass
from models.workload import Criticality


@dataclass
class ScenarioMetrics:

    scenario: str

    total_utility: float = 0.0

    workloads_completed: int = 0
    workloads_infeasible: int = 0

    critical_workloads_successful: int = 0
    critical_workloads_total: int = 0

    adaptations: int = 0
    migrations: int = 0
    degradations: int = 0
    fallbacks: int = 0
    suspensions: int = 0


def calculate_scenario_metrics(
    scenario_name,
    decisions,
    system
):

    metrics = ScenarioMetrics(
        scenario=scenario_name
    )

    for decision in decisions:

        # No feasible allocation
        if decision["location"] is None:

            metrics.workloads_infeasible += 1

            workload = next(
                w for w in system.workloads
                if w.name == decision["workload"]
            )

            if workload.criticality == Criticality.VERY_HIGH:
                metrics.critical_workloads_total += 1

            continue

        # Workload successfully allocated
        metrics.workloads_completed += 1

        workload = next(
            w for w in system.workloads
            if w.name == decision["workload"]
        )

        # Mission utility
        metrics.total_utility += decision["details"]["utility"]

        # Critical workload tracking
        if workload.criticality == Criticality.VERY_HIGH:

            metrics.critical_workloads_total += 1

            metrics.critical_workloads_successful += 1

        # Adaptation
        if decision["adapted"]:

            metrics.adaptations += 1

            adaptation_type = decision.get(
                "adaptation_type",
                ""
            )

            if "Migration" in adaptation_type:
                metrics.migrations += 1

            if "Degradation" in adaptation_type:
                metrics.degradations += 1

            if "Fallback" in adaptation_type:
                metrics.fallbacks += 1

            if "Suspension" in adaptation_type:
                metrics.suspensions += 1

    return metrics