from baselines.static_baseline import STATIC_ACTIONS

from simulation.scenarios import (
    normal_conditions,
    network_degradation,
    edge_overload,
    cloud_failure,
    resource_pressure,
    emergency_mission,
    severe_degradation,
    recovery
)

from simulation.timeline import create_timeline
from simulation.records import TimeStepRecord
from orchestrator.feasibility import (
    has_enough_resources,
    network_is_feasible,
    meets_deadline
)
from orchestrator.utility import calculate_utility


SCENARIO_FUNCTIONS = {
    "Normal": normal_conditions,
    "Network Degradation": network_degradation,
    "Edge Overload": edge_overload,
    "Cloud Failure": cloud_failure,
    "Resource Pressure": resource_pressure,
    "Emergency Mission": emergency_mission,
    "Severe Degradation": severe_degradation,
    "Recovery": recovery
}


def run_static_timeline(system):

    timeline = create_timeline()
    records = []

    for step in timeline:

        scenario_function = SCENARIO_FUNCTIONS[
            step.scenario
        ]

        scenario_function(system)

        total_utility = 0
        completed = 0
        infeasible = 0

        for workload in system.workloads:

            location, mode = STATIC_ACTIONS[
                workload.name
            ]

            feasible = (
                has_enough_resources(
                    workload,
                    location,
                    mode,
                    system
                )
                and network_is_feasible(
                    workload,
                    location,
                    system
                )
                and meets_deadline(
                    workload,
                    location,
                    mode,
                    system
                )
            )

            if feasible:

                utility = calculate_utility(
                    workload,
                    mode,
                    system.mission.phase
                )

                total_utility += utility
                completed += 1

            else:
                infeasible += 1

        records.append(
            TimeStepRecord(
                time=step.time,
                scenario=step.scenario,
                mission_utility=total_utility,
                workloads_completed=completed,
                workloads_infeasible=infeasible,
                adaptations=0,
                migrations=0,
                degradations=0,
                fallbacks=0,
                suspensions=0
            )
        )

    return records