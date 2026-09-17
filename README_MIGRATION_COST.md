# Migration Cost Implementation

The proposed policy now models migration as an analytical soft cost whenever a workload changes execution location.

## Model

For workload state size S (MB) and effective migration bandwidth B (MB/s):

`transfer_time_ms = (S / B) * 1000`

The migration time is:

`T_mig = transfer_time_ms + path_latency_ms + orchestration_overhead_ms`

For Edge-to-Edge migration, the model uses a fixed analytical path latency of 20 ms. Other location changes use the current network latency.

The normalized migration cost is:

`C_mig = (T_mig / deadline) * 20`

A migration is accepted when the improvement in operating score exceeds `C_mig`. If the current placement is infeasible, migration is permitted as a recovery action.

Migration cost is not a hard feasibility constraint and is not claimed to represent physical aircraft communication energy or an actual state-transfer implementation.

Default parameters:
- Migration bandwidth: 50 MB/s
- Edge-to-edge latency: 20 ms
- Orchestration overhead: 5 ms
- Cost scale: 20
- Default workload state size: 1 MB

The dedicated `mobility_handover.py` experiment isolates Edge 1 / Edge 2 handover under cloud unavailability.
