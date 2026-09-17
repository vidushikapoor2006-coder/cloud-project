from enum import Enum
from dataclasses import dataclass


class MissionPhase(Enum):
    TAKEOFF = "Takeoff"
    CRUISE = "Cruise"
    APPROACH = "Approach"
    LANDING = "Landing"
    EMERGENCY = "Emergency"


@dataclass
class MissionState:
    phase: MissionPhase
    emergency: bool = False


@dataclass
class NetworkState:
    latency: float
    bandwidth: float
    packet_loss: float
    connected: bool = True