"""
AWS proof-of-concept latency measurement (requested by the reviewers).

NOT RUN BY THE AUTHORS' REVISION ASSISTANT: no AWS credentials were available
in the revision environment.  Run it in your AWS account and paste the output
(results/aws/aws_latency.csv + summary) into the paper.

Measures, for N messages:
  1. MQTT publish latency to AWS IoT Core (QoS 1, i.e. until PUBACK), via
     execution/aws_iot_client.publish_mission();
  2. end-to-end ingest latency: publish -> record visible in DynamoDB
     (IoT rule -> Lambda -> DynamoDB), by polling the table with boto3;
  3. Lambda execution duration (Average/p95/Maximum) from CloudWatch metric
     AWS/Lambda Duration over the measurement window.

Prerequisites
  pip install AWSIoTPythonSDK boto3
  export AWS_IOT_ENDPOINT=... AWS_IOT_ROOT_CA=... AWS_IOT_CERT=... AWS_IOT_PRIVATE_KEY=...
  export AWS_REGION=ap-south-1
  export AWS_DDB_TABLE=<table written by the Lambda>
  export AWS_DDB_KEY=mission_id            # partition key used by the Lambda
  export AWS_LAMBDA_NAME=<function name>
  aws credentials for boto3 (DynamoDB read, CloudWatch read)

Usage
  python -m experiments.aws_latency_probe --n 100 --interval 0.5
"""

import argparse
import csv
import datetime as dt
import os
import statistics
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution import aws_iot_client  # noqa: E402


def pct(values, q):
    v = sorted(values)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--timeout", type=float, default=10.0)
    a = ap.parse_args()

    import boto3
    region = os.environ.get("AWS_REGION", "ap-south-1")
    table = boto3.resource("dynamodb", region_name=region).Table(
        os.environ["AWS_DDB_TABLE"])
    key = os.environ.get("AWS_DDB_KEY", "mission_id")
    lambda_name = os.environ.get("AWS_LAMBDA_NAME")

    aws_iot_client.connect()
    start_window = dt.datetime.now(dt.timezone.utc)
    rows = []
    for i in range(a.n):
        mid = f"latency-probe-{uuid.uuid4().hex[:12]}"
        t0 = time.perf_counter()
        publish_ms = aws_iot_client.publish_mission(
            mission_id=mid, workload="Weather Analysis", mode="Full",
            mission_phase="CRUISE", location="AWS_Cloud", verbose=False)
        e2e_ms = None
        while time.perf_counter() - t0 < a.timeout:
            if table.get_item(Key={key: mid}).get("Item"):
                e2e_ms = (time.perf_counter() - t0) * 1000.0
                break
            time.sleep(0.02)
        rows.append({"i": i, "mission_id": mid, "publish_ms": publish_ms,
                     "end_to_end_ms": e2e_ms})
        time.sleep(a.interval)
    aws_iot_client.disconnect()
    end_window = dt.datetime.now(dt.timezone.utc)

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "aws")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "aws_latency.csv"), "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)

    pub = [r["publish_ms"] for r in rows]
    e2e = [r["end_to_end_ms"] for r in rows if r["end_to_end_ms"] is not None]
    print(f"MQTT publish (QoS1) ms: mean {statistics.mean(pub):.1f} "
          f"p95 {pct(pub, .95):.1f} max {max(pub):.1f} (n={len(pub)})")
    if e2e:
        print(f"End-to-end IoT->Lambda->DynamoDB ms: mean {statistics.mean(e2e):.1f} "
              f"p95 {pct(e2e, .95):.1f} max {max(e2e):.1f} "
              f"(n={len(e2e)}, lost/timeout={len(rows) - len(e2e)})")
    if lambda_name:
        cw = boto3.client("cloudwatch", region_name=region)
        stats = cw.get_metric_statistics(
            Namespace="AWS/Lambda", MetricName="Duration",
            Dimensions=[{"Name": "FunctionName", "Value": lambda_name}],
            StartTime=start_window - dt.timedelta(minutes=1),
            EndTime=end_window + dt.timedelta(minutes=5), Period=3600,
            Statistics=["Average", "Maximum", "SampleCount"],
            ExtendedStatistics=["p95"])
        print("Lambda Duration (CloudWatch):", stats.get("Datapoints"))
    print("raw data:", os.path.join(out, "aws_latency.csv"))


if __name__ == "__main__":
    main()
