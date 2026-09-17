from execution.aws_iot_client import connect, publish_mission, disconnect


connect()

publish_mission(
    mission_id="integration-test-001",
    workload="Weather Analysis",
    mode="Full",
    mission_phase="CRUISE",
    location="AWS_CLOUD"
)

disconnect()