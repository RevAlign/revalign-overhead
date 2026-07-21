#!/usr/bin/env bash
#
# Open-vocabulary example: detect an object that has NO pretrained model, just by
# describing it. This uses the `vision` backend (an open-vocabulary vision LLM).
#
# HONESTY: swimming pools are the only benchmarked object. ANY object you describe here
# will run, but its recall and precision are UN-BENCHMARKED; there are no accuracy numbers
# for it. Treat the output as a strong first pass to eyeball against the annotated
# detected.png, not as a validated count.
#
# Cost: Esri tiles are free. The vision LLM costs a few cents per scan; it slices the
# stitched canvas into chunks and makes one call per chunk. The tool prints an estimated
# cost at the end. This small demo is a couple of cents.
#
# Requires an API key for the provider you pick:
#   export ANTHROPIC_API_KEY=...          # default provider (anthropic)
#   # or use OpenAI: export OPENAI_API_KEY=...  and add  --provider openai  below.

set -euo pipefail

: "${ANTHROPIC_API_KEY:?Set ANTHROPIC_API_KEY first (or switch to --provider openai with OPENAI_API_KEY)}"

# Center-pivot irrigation circles over farmland in Nebraska. These huge crop circles
# (~400 m across) are easy to see from orbit, which makes them a clean first demo.
# Zoom 16 keeps the canvas small and the run to a single cheap vision call.
python -m birdseye \
    --backend vision \
    --provider anthropic \
    --object-name "center-pivot irrigation circle (a large round green or brown crop field)" \
    --object-size 400 \
    --out out_custom \
    41.8800 -101.7200 3000 16

# Another idea: aboveground storage tanks at a tank farm (bright circular tops, ~20 m).
# Small objects need high zoom, so scan a tighter area at zoom 19. Swap in:
#
#     python -m birdseye \
#         --backend vision \
#         --object-name "aboveground storage tank (a bright circular tank top viewed from above)" \
#         --object-size 20 \
#         --out out_tanks \
#         <lat> <lon> 800 19
