"""Cumulative (joint) resource accounting within one decision step (Eq. (12))."""

from models.workload import ExecutionMode
from orchestrator.feasibility import (
    get_resource_for_location,
    scaled_requirements,
)


def get_resource_requirements(workload, mode):
    if mode == ExecutionMode.SUSPENDED:
        return 0, 0, 0
    return scaled_requirements(workload, mode)


def can_allocate(
    workload,
    location,
    mode,
    system,
    allocations
):
    resource = get_resource_for_location(
        location,
        system
    )

    if resource is None:
        return False

    if not resource.available and mode != ExecutionMode.SUSPENDED:
        return False

    compute, memory, energy = get_resource_requirements(
        workload,
        mode
    )

    used = allocations.get(location, {})

    # CPU constraint
    if used.get("cpu", 0) + compute > resource.cpu_available + 1e-9:
        return False

    # Memory constraint
    if used.get("memory", 0) + memory > resource.memory_available + 1e-9:
        return False

    # Energy constraint
    if used.get("energy", 0) + energy > resource.energy_available + 1e-9:
        return False

    return True


def allocate(
    workload,
    location,
    mode,
    allocations
):
    compute, memory, energy = get_resource_requirements(
        workload,
        mode
    )

    if location not in allocations:
        allocations[location] = {
            "cpu": 0,
            "memory": 0,
            "energy": 0
        }

    allocations[location]["cpu"] += compute
    allocations[location]["memory"] += memory
    allocations[location]["energy"] += energy
