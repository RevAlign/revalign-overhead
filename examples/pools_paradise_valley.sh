#!/usr/bin/env bash
#
# Validated example: backyard swimming pools in Paradise Valley, Arizona.
#
# This is the ONLY object revalign-overhead has been benchmarked on. On free Esri imagery,
# pool recall is roughly 60 to 75 percent (not perfect). A blue-water color gate
# quarantines likely false positives as "tentative", so the "confirmed" rows stay clean.
# Always open detected.png and check the rings against the imagery.
#
# Backend: yolo, a local model that runs at $0 per scan. On the FIRST run it downloads
# the pool weights once from Hugging Face (mozilla-ai/swimming-pool-detector); every run
# after that is offline and free. Esri World Imagery tiles are free and need no key.
#
# Requires the yolo extra (ultralytics + weights are AGPL-3.0):
#   pip install -e ".[yolo]"        # or: pip install ultralytics huggingface_hub
#
# What to expect: a ~510 m square scan at zoom 19, a handful of confirmed pools plus some
# tentative ones, and three files in ./out_pools (detections.csv, canvas.png, detected.png).
# First run takes a minute or two (weights download + model load); later runs are faster.

set -euo pipefail

python -m revalign_overhead \
    --object pool \
    --backend yolo \
    --out out_pools \
    33.5400 -111.9500 510
