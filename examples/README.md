# Examples

Runnable examples for `birdseye`. Each one is a small, honest demo you can copy,
run, and eyeball against the proof image it writes.

## Before you start

Install the package (from the repo root):

```bash
pip install -e .                # core (Pillow); enough for the vision backend
pip install -e ".[yolo]"        # adds the free local YOLO backend (ultralytics + huggingface_hub, AGPL-3.0)
```

The scripts call `python -m birdseye`. Run them from the repo root, e.g.:

```bash
bash examples/pools_paradise_valley.sh
```

## What's here

| File | Backend | Needs a key? | What it does |
|------|---------|--------------|--------------|
| `pools_paradise_valley.sh` | `yolo` (local, $0) | No | The validated pool scan over Paradise Valley, Arizona. |
| `custom_object.sh` | `vision` (open-vocab) | Yes (`ANTHROPIC_API_KEY`) | Detects an object you describe in a sentence, no model needed. |
| `add_an_object.md` | either | depends | Tutorial: register a reusable object in the `OBJECTS` table. |

## Cost and imagery

- **Imagery is free.** Both backends pull Esri World Imagery tiles, which need no API
  key. Free Esri imagery caps out around zoom 19 in many areas; the tool auto-falls
  back a zoom level when a tile is missing, so rural scans quietly drop to lower detail.
- **The `yolo` backend is $0 per scan.** It runs a local model. The pool weights download
  once from Hugging Face on the first run, then every run is offline and free.
- **The `vision` backend costs a few cents per scan.** It slices the stitched canvas into
  chunks and makes one vision-LLM call per chunk. A small scan is a couple of cents; a
  large one is more. The tool prints an estimated cost at the end of every run.

## One honest caveat

**Swimming pools are the only object this tool has been benchmarked on.** On free Esri
imagery, pool recall is roughly 60 to 75 percent (not perfect); a blue-water color gate
quarantines likely false positives as `tentative` so the `confirmed` rows stay clean.

Every other object, whether it is the bundled `solar` spec or something you describe with
`--object-name`, runs through the open-vocab `vision` backend but is **un-benchmarked**.
There are no accuracy numbers for it. Treat those results as a strong first pass to check
against the annotated `detected.png`, not as a validated count.

## What each run writes

Every run writes three files into its output directory (`--out`, default `./out`):

| File | Contents |
|------|----------|
| `detections.csv` | One row per detection: `lat, lon, status, model_conf, color_score, gmaps, note`. `status` is `confirmed` or `tentative`. `gmaps` is a ready-to-click Google Maps link. |
| `canvas.png` | The raw stitched satellite image the tool scanned. |
| `detected.png` | The same image with rings drawn on it: green for confirmed, amber for tentative. This is your proof image; always look at it. |

The CSV opens straight in a spreadsheet.

---

Built by RevAlign (https://revalign.io).
