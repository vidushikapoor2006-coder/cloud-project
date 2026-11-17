"""Manual AWS IoT connectivity test (requires valid AWS IoT credentials).

Run explicitly with: python aws_test.py
This module is intentionally safe to import during test discovery.
"""


def main():
    from execution.aws_iot_client import connect, publish_mission, disconnect

    connect()
    try:
        publish_mission(
            mission_id="integration-test-001",
            workload="Weather Analysis",
            mode="Full",
            mission_phase="CRUISE",
            location="AWS_CLOUD",
        )
    finally:
        disconnect()


if __name__ == "__main__":
    main()
