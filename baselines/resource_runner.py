from baselines.resource_aware import (
    select_resource_aware_action
)

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


def run_resource_aware_timeline(system):

    timeline = create_timeline()
    records = []

    for step in timeline:

        scenario_function = SCENARIO_FUNCTIONS[
            step.scenario
        ]

        scenario_function(system)

        allocations = {}

        total_utility = 0
        completed = 0
        infeasible = 0

        workloads = sorted(
            system.workloads,
            key=lambda w: w.criticality.value,
            reverse=True
        )

        for workload in workloads:

            action = select_resource_aware_action(
                workload,
                system,
                allocations
            )

            if action is None:
                infeasible += 1
                continue

            location, mode = action

            utility = calculate_utility(
                workload,
                mode,
                system.mission.phase
            )

            total_utility += utility
            completed += 1

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