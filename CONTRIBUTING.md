# Contributing to birdseye

Thanks for taking a look. birdseye is small on purpose: one engine file, the
standard library where possible, and two detection backends. This guide gets you
a dev environment, explains how the pieces fit, and shows how to add a new object
or propose a pretrained model.

Built by RevAlign (https://revalign.io).

## Ground rules (read these first)

- **Be honest about accuracy.** Only swimming pools are benchmarked and validated
  end to end (roughly 60 to 75 percent recall on backyard pools in the test area,
  with false positives quarantined as `tentative`). Every other object runs through
  the open-vocabulary vision backend and is un-benchmarked. If you add or document
  an object, say so plainly. Do not imply accuracy numbers we do not have.
- **Free imagery has limits.** Esri World Imagery caps out around zoom 19 in many
  areas; the tool auto-falls-back a zoom level when a tile is missing. State real
  limitations rather than papering over them.
- **Cite only public facts.** Esri, Web Mercator, OpenStreetMap tile math, YOLO,
  and SAHI-style sliced inference are fair game. Keep it public.

## Dev environment

You need Python 3.9 or newer.

```bash
git clone https://github.com/RevAlign/birdseye
cd birdseye

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Core install (the open-vocabulary vision backend, editable):
pip install -e .

# Add the local YOLO backend (pulls ultralytics + huggingface_hub):
pip install -e ".[yolo]"
```

The core install only needs Pillow. The vision backend talks to the Anthropic or
OpenAI HTTP APIs with the standard library, so no vendor SDK is required; you set
`ANTHROPIC_API_KEY` (or `OPENAI_API_KEY` with `--provider openai`) at runtime. The
YOLO backend is what the `[yolo]` extra is for.

Smoke-test that it imports and the CLI builds:

```bash
python -m birdseye --help
pytest -q
```

A first real run, once you have a key set:

```bash
export ANTHROPIC_API_KEY=...        # only for the vision backend
python -m birdseye --object pool 33.5400 -111.9500 510
```

Output lands in `./out`: `detections.csv`, the stitched `canvas.png`, and an
annotated `detected.png` (green circles are confirmed, amber are tentative).

## How the pieces fit

Everything lives in `birdseye/detect.py`, split into labelled sections. Reading
them top to bottom is the fastest way to understand the flow:

| Section | What it does |
|---------|--------------|
| **config** | Tile URL, chunk sizes, dedup radius, model names. Tunables. |
| **object specs** | `HSVFilter`, `ObjectSpec`, the `PROMPT_TEMPLATE`, the `OBJECTS` registry, and `spec_for()` which resolves what to look for. |
| **tile math** | `meters_per_px`, `deg2tile`, `fetch_tile`, `build_canvas` (stitches the scan and does the zoom fallback), `canvas_to_latlon` (pixel to georeference). |
| **vision (LLM) backend** | `vision_detect` and helpers. Open-vocabulary, describe any object, a few cents per scan. |
| **YOLO backend** | `_load_yolo`, `yolo_detect_canvas`. Local, 0 dollars per scan, sliced (SAHI-style) native-resolution inference. |
| **precision filter** | `color_score`. The deterministic HSV gate that turns noisy proposals into confirmed vs tentative buckets. |
| **pipeline** | `detect()`. Stitches, runs a backend, dedups across windows, applies the color gate, georeferences, writes the CSV and proof image. |
| **CLI** | `main()`. The argparse front door. |

The core idea worth internalizing: the scan is sliced into fixed-ground-size
windows so the target renders at a near-constant pixel size everywhere, because
Web Mercator meters-per-pixel changes with latitude. Native-resolution windows
beat one downscaled pass, which is why small objects stay detectable.

## Adding an object

Most objects need no code beyond one registry entry. Add an `ObjectSpec` to the
`OBJECTS` dict in the **object specs** section:

```python
"trampoline": ObjectSpec(
    name="round backyard trampoline (a dark circular mat with a frame)",
    size_m=4.0,                         # typical real-world width in meters
    prompt=PROMPT_TEMPLATE,             # or a bespoke prompt string
    color_filter=None,                  # add an HSVFilter only if the object has a reliable signature color
    yolo_repo=None,                     # set only if you are bundling a pretrained YOLO model
),
```

Then run it through the open-vocabulary backend:

```bash
python -m birdseye --backend vision --object trampoline 33.54 -111.95 510
```

Notes:

- You do not have to edit the registry at all for a one-off. `--object-name` plus
  `--object-size` builds an ad-hoc spec on the fly (see `spec_for`).
- Add a `color_filter` (an `HSVFilter`) only when the object has a dependable
  color, like pool water. PIL HSV channels are 0 to 255. Without a signature
  color, leave it `None`; the pipeline then buckets on model confidence alone.
- If you add an object, document it honestly in the README as un-benchmarked
  unless you have actually validated it against ground truth.

## Proposing a new pretrained model

The YOLO backend loads weights from a Hugging Face repo named in the spec
(`yolo_repo`, plus `yolo_weights` for the filename inside it). To propose one:

1. Point `yolo_repo` at a public HF repo that hosts an ultralytics-compatible
   `.pt` file, and set `yolo_weights` if the filename is not `model.pt`.
2. Validate it against real ground truth in at least one area and report the
   numbers you saw (recall, false-positive behavior, the region you tested).
   Attach the CSV and the annotated proof image if you can.
3. Open a PR that adds the spec and states plainly what is and is not validated.

We would rather ship a model with honest, modest numbers than one with a
confident claim we cannot back up.

## Coding style

- **Standard library first.** Pillow is the only hard runtime dependency; keep it
  that way. Heavy deps (ultralytics, huggingface_hub) stay lazy-imported inside
  the YOLO backend so the core install stays light.
- **No em dashes** anywhere, in code, comments, or docs. Use commas, semicolons,
  or parentheses.
- **Keep sections labelled.** New code goes under the matching section banner in
  `detect.py`, or a new banner if it is genuinely a new stage.
- **Match what is there.** Short functions, direct names, comments that explain
  the why (the scale-invariance trick, the color gate) rather than restating code.
- **No network in tests.** Unit tests must run offline with no API keys and no
  model download. See `tests/test_smoke.py` for the pattern.

## Submitting a change

1. Fork, branch, make the change.
2. Run `python -m birdseye --help` and `pytest -q` locally.
3. Open a PR describing what changed and, for any detector work, what you
   validated and what remains un-benchmarked.

CI runs a lightweight check on every push and PR: it compiles the package, imports
it, and smoke-tests the CLI. No secrets, no network, no model download.
