from models.workload import Location, ExecutionMode


STATIC_ACTIONS = {
    "Obstacle Detection": (
        Location.ONBOARD,
        ExecutionMode.FULL
    ),

    "Navigation": (
        Location.ONBOARD,
        ExecutionMode.FULL
    ),

    "Weather Analysis": (
        Location.CLOUD,
        ExecutionMode.FULL
    ),

    "Video Analytics": (
        Location.CLOUD,
        ExecutionMode.FULL
    ),

    "Flight Logging": (
        Location.CLOUD,
        ExecutionMode.FULL
    )
}


def run_static_baseline(system):
    decisions = []

    for workload in system.workloads:

        location, mode = STATIC_ACTIONS[
            workload.name
        ]

        decisions.append({
            "workload": workload.name,
            "location": location,
            "mode": mode
        })

    return decisions