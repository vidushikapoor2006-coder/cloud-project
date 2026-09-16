from models.mission import MissionPhase
EDGE_POSITIONS = {
    "Edge1": 0.0,   # km
    "Edge2": 10.0   # km
}
def get_edge_distances(evtol_position):
    return {
        "Edge1": abs(evtol_position - EDGE_POSITIONS["Edge1"]),
        "Edge2": abs(evtol_position - EDGE_POSITIONS["Edge2"])
    }
def get_edge_latency(base_latency, distance):
    return base_latency + (distance * 5)

def normal_conditions(system):
    """
    Normal operating conditions.
    """

    system.onboard.cpu_used = 20
    system.onboard.memory_used = 20
    system.onboard.energy_available = 100
    system.onboard.available = True

    system.edge_1.cpu_used = 30
    system.edge_1.memory_used = 25
    system.edge_1.energy_available = 100
    system.edge_1.available = True

    system.edge_2.cpu_used = 40
    system.edge_2.memory_used = 30
    system.edge_2.energy_available = 100
    system.edge_2.available = True

    system.cloud.cpu_used = 50
    system.cloud.memory_used = 40
    system.cloud.energy_available = 100
    system.cloud.available = True

    system.network.latency = 50
    system.network.bandwidth = 100
    system.network.packet_loss = 1
    system.network.connected = True

    system.mission.phase = MissionPhase.CRUISE
    system.mission.emergency = False


def network_degradation(system):
    """
    Network becomes severely degraded while
    computing resources remain available.
    """

    normal_conditions(system)

    system.network.latency = 300
    system.network.bandwidth = 40
    system.network.packet_loss = 20


def edge_overload(system):
    """
    Both edge nodes become heavily loaded.
    """

    normal_conditions(system)

    system.edge_1.cpu_used = 95
    system.edge_1.memory_used = 90

    system.edge_2.cpu_used = 90
    system.edge_2.memory_used = 85


def cloud_failure(system):
    """
    AWS cloud becomes unavailable.
    """

    normal_conditions(system)

    system.cloud.available = False


def resource_pressure(system):
    """
    Moderate system-wide resource pressure.

    Unlike severe degradation, the system is still
    partially operational.

    This scenario tests whether the orchestrator
    can preserve important workloads while reducing
    lower-value workloads.
    """

    normal_conditions(system)

    # Onboard resource pressure
    system.onboard.cpu_used = 70
    system.onboard.memory_used = 70
    system.onboard.energy_available = 45

    # Edge nodes are also constrained
    system.edge_1.cpu_used = 80
    system.edge_1.memory_used = 75

    system.edge_2.cpu_used = 85
    system.edge_2.memory_used = 80

    # Cloud remains available but network quality is poor
    system.cloud.cpu_used = 75
    system.cloud.memory_used = 70

    system.network.latency = 180
    system.network.bandwidth = 60
    system.network.packet_loss = 10
    system.network.connected = True


def severe_degradation(system):
    """
    Extreme system degradation.

    Onboard and edge resources are heavily constrained,
    cloud is unavailable, and the network is disconnected.
    """

    normal_conditions(system)

    system.onboard.cpu_used = 90
    system.onboard.memory_used = 90
    system.onboard.energy_available = 25

    system.edge_1.cpu_used = 95
    system.edge_1.memory_used = 90

    system.edge_2.cpu_used = 95
    system.edge_2.memory_used = 90

    system.cloud.available = False

    system.network.latency = 400
    system.network.bandwidth = 20
    system.network.packet_loss = 30
    system.network.connected = False


def emergency_mission(system):
    """
    Emergency mission phase.

    Computing/network conditions remain usable,
    but mission priorities change.

    The mission-aware policy should respond to the
    changed mission context.
    """

    normal_conditions(system)

    system.mission.phase = MissionPhase.EMERGENCY
    system.mission.emergency = True


def recovery(system):
    """
    System recovers to normal operating conditions.
    """

    normal_conditions(system)