#!/usr/bin/env bash
# Reproduce every result of the revised paper from scratch (~15 min on 2 cores).
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pytest -q tests
python3 -m experiments.run_experiments --legacy --tag legacy
python3 -m experiments.analyze --tag legacy
python3 -m experiments.run_experiments --trials 30 --tag main
python3 -m experiments.run_experiments --ablation --trials 30 --tag ablation
python3 -m experiments.analyze --tag ablation
python3 -m experiments.analyze --tag main
python3 -m experiments.sensitivity --trials 30
python3 -m experiments.benchmark_runtime      # run on an idle machine
python3 -m experiments.make_tables
python3 -m experiments.make_figures
echo "Done. Tables: generated/  Figures: figures/  Raw data: results/"
