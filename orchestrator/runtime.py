from models.workload import (
    Workload,
    Location,
    ExecutionMode,
    WorkloadState
)


def update_workload_state(workload, new_location, new_mode):

    old_location = workload.current_location
    old_mode = workload.current_mode

    workload.previous_location = old_location
    workload.previous_mode = old_mode

    workload.current_location = new_location
    workload.current_mode = new_mode

    # Determine runtime state

    if new_mode == ExecutionMode.SUSPENDED:
        workload.state = WorkloadState.SUSPENDED

    elif new_mode == ExecutionMode.FALLBACK:
        workload.state = WorkloadState.FALLBACK

    elif new_mode == ExecutionMode.REDUCED:
        workload.state = WorkloadState.DEGRADED

    elif old_location != new_location:
        workload.state = WorkloadState.MIGRATING

    else:
        workload.state = WorkloadState.RUNNING


def was_adapted(workload):
    return (
        workload.previous_location != workload.current_location
        or workload.previous_mode != workload.current_mode
    )