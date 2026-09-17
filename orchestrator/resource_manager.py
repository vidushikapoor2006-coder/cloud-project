from models.workload import ExecutionMode
from orchestrator.feasibility import get_resource_for_location


def get_resource_requirements(workload, mode):
    compute = workload.compute_requirement
    memory = workload.memory_requirement
    energy = workload.energy_requirement

    if mode == ExecutionMode.REDUCED:
        compute *= 0.5
        memory *= 0.5
        energy *= 0.5

    elif mode == ExecutionMode.FALLBACK:
        compute *= 0.2
        memory *= 0.2
        energy *= 0.2

    elif mode == ExecutionMode.SUSPENDED:
        compute = 0
        memory = 0
        energy = 0

    return compute, memory, energy


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

    compute, memory, energy = get_resource_requirements(
        workload,
        mode
    )

    current_cpu = allocations.get(
        location,
        {}
    ).get("cpu", 0)

    current_memory = allocations.get(
        location,
        {}
    ).get("memory", 0)

    current_energy = allocations.get(
        location,
        {}
    ).get("energy", 0)

    # --------------------------------------------------------
    # CPU constraint
    # --------------------------------------------------------

    if current_cpu + compute > resource.cpu_available:
        return False

    # --------------------------------------------------------
    # Memory constraint
    # --------------------------------------------------------

    if current_memory + memory > resource.memory_available:
        return False

    # --------------------------------------------------------
    # Energy constraint
    # --------------------------------------------------------

    if current_energy + energy > resource.energy_available:
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