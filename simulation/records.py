from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class TimeStepRecord:
    time: int
    scenario: str
    mission_utility: float
    workloads_completed: int
    workloads_infeasible: int
    adaptations: int
    migrations: int
    degradations: int
    fallbacks: int
    suspensions: int
    decisions: List[Dict[str, Any]] = None