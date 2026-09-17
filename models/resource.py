from dataclasses import dataclass


@dataclass
class ResourceState:
    name: str
    cpu_capacity: float
    cpu_used: float
    memory_capacity: float
    memory_used: float
    energy_available: float
    available: bool = True

    @property
    def cpu_available(self):
        return self.cpu_capacity - self.cpu_used

    @property
    def memory_available(self):
        return self.memory_capacity - self.memory_used