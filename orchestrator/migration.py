"""Analytical migration model (Eqs. (14)-(15) of the revised paper).

Unchanged from the original submission except that it now lives in its own
module so that the feasibility layer can use the migration time in the
migration-aware deadline constraint (Eq. (11)).
"""

import config


def is_migration(workload, new_location):
    """A location change of an already-placed workload is a migration.

    The first placement of a workload (previous_location is None) is an
    initial placement and is not charged.
    """
    old_location = workload.current_location
    return not (
        old_location is None
        or new_location is None
        or old_location == new_location
        or getattr(workload, "previous_location", None) is None
    )


def calculate_migration_cost(workload, old_location, new_location, system):
    """Return analytical migration time T_mig [ms] and normalised cost C_mig.

    T_mig = s_i / min(B_mig, B_t) * 1000 + L_path + T_orch
    C_mig = lambda_mig * T_mig / D_i
    """
    if (
        old_location is None
        or old_location == new_location
        or getattr(workload, "previous_location", None) is None
    ):
        return {"migration_time_ms": 0.0, "migration_cost": 0.0}

    state_size_mb = max(float(getattr(workload, "state_size_mb", 1.0)), 0.0)
    effective_bandwidth = max(
        min(config.MIGRATION_BANDWIDTH, float(system.network.bandwidth)),
        1e-6,
    )
    transfer_time_ms = (state_size_mb / effective_bandwidth) * 1000.0

    if (old_location.value.startswith("Edge_")
            and new_location.value.startswith("Edge_")):
        path_latency_ms = config.EDGE_TO_EDGE_LATENCY_MS
    else:
        path_latency_ms = float(system.network.latency)

    migration_time_ms = (
        transfer_time_ms + path_latency_ms + config.MIGRATION_OVERHEAD_MS
    )
    migration_cost = (
        migration_time_ms / max(workload.deadline, 1.0)
    ) * config.MIGRATION_COST_SCALE

    return {
        "migration_time_ms": migration_time_ms,
        "migration_cost": migration_cost,
    }


def raw_migration_time_ms(workload, old_location, new_location, system):
    """T_mig for an explicit location pair (used by the look-ahead policy).

    Same formula as calculate_migration_cost, without the initial-placement
    exemption.  Returns 0 when there is no location change.
    """
    if old_location is None or new_location is None or old_location == new_location:
        return 0.0
    effective_bandwidth = max(
        min(config.MIGRATION_BANDWIDTH, float(system.network.bandwidth)), 1e-6)
    transfer = (max(float(workload.state_size_mb), 0.0)
                / effective_bandwidth) * 1000.0
    if (old_location.value.startswith("Edge_")
            and new_location.value.startswith("Edge_")):
        path = config.EDGE_TO_EDGE_LATENCY_MS
    else:
        path = float(system.network.latency)
    return transfer + path + config.MIGRATION_OVERHEAD_MS
