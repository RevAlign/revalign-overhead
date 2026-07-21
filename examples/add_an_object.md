# Adding a reusable object

`--object-name` is great for a one-off scan. When you want an object available by a short
name every time (with its own tuned prompt and, optionally, a color gate or a pretrained
model), register it in the `OBJECTS` table in `birdseye/detect.py`.

Once registered, it shows up in `--help`, in the `Known:` list, and is runnable as
`--object <your_key>`.

## The `ObjectSpec` fields

Each entry in `OBJECTS` is an `ObjectSpec`. Here is every field:

| Field | Type | Required | What it is |
|-------|------|----------|------------|
| `name` | str | yes | Human name of the object. It is injected into the prompt as `{name}`, so make it descriptive, e.g. `"backyard swimming pool (a blue/teal water rectangle or freeform shape)"`. |
| `size_m` | float | yes | Typical real-world width in meters. The pipeline uses this to slice the scan into fixed-ground-size windows so the object renders at a near-constant pixel size everywhere, and to tell the model how many pixels wide (`{obj_px}`) to expect. |
| `prompt` | str | yes | The vision-LLM instruction. Use the shared `PROMPT_TEMPLATE` or write your own (see below). |
| `color_filter` | `HSVFilter` or `None` | no | An optional deterministic color gate that confirms or quarantines each detection. Use it for strongly-colored objects; leave `None` otherwise. |
| `yolo_repo` | str or `None` | no | Hugging Face repo of a pretrained YOLO model for this object, if one exists. Leave `None` and the object runs on the open-vocab `vision` backend. |
| `yolo_weights` | str | no | Weights filename inside `yolo_repo`. Defaults to `"model.pt"`. |

## Step 1: pick a prompt

You have two choices.

**Reuse `PROMPT_TEMPLATE`.** It already asks for strict JSON and gets `{name}`, `{wpx}`,
`{hpx}`, `{mpp}`, and `{obj_px}` filled in per chunk. This is the easy path:

```python
prompt=PROMPT_TEMPLATE,
```

**Write your own** when you want to add "ignore these look-alikes" hints, like the bundled
`pool` spec does. Two rules if you write a custom prompt:

- Keep the placeholders you need (`{name}`, `{wpx}`, `{hpx}`, `{mpp}`, `{obj_px}`). They are
  filled in with `str.format()` at run time.
- Because of `str.format()`, any **literal** JSON braces must be **doubled**: write `{{` and
  `}}`. Keep the strict-JSON output contract intact, since the parser expects
  `{"detections":[{"x":...,"y":...,"confidence":...,"note":"..."}]}`.

## Step 2 (optional): tune a color gate

`HSVFilter` counts what fraction of a small patch around each detection falls inside an HSV
window, and only confirms the detection if that fraction clears `min_frac`. PIL's HSV
channels run 0 to 255 (note: hue is 0 to 255 here, not 0 to 360).

| Field | Default | Meaning |
|-------|---------|---------|
| `hue_lo`, `hue_hi` | required | Low and high hue bound of the object's signature color. |
| `sat_min` | required | Minimum saturation (filters out washed-out gray look-alikes). |
| `val_min` | required | Minimum brightness (filters out dark shadows). |
| `min_frac` | `0.10` | Fraction of the patch that must be in-window to confirm. |
| `patch_r` | `16` | Half-size in pixels of the sampled patch around the detection. |

Detections that pass become `confirmed`; the rest become `tentative` (still written to the
CSV, just flagged). Leave `color_filter=None` for objects without a reliable single color.

## Step 3: register it

Add your spec to the `OBJECTS` dict in `birdseye/detect.py`. Example, a blue emergency
roof tarp (bright blue, so a color gate helps a lot):

```python
OBJECTS: dict[str, ObjectSpec] = {
    "pool": ObjectSpec(...),      # existing
    "solar": ObjectSpec(...),     # existing

    "tarp": ObjectSpec(
        name="blue emergency roof tarp (a bright blue rectangle on a roof)",
        size_m=8.0,
        prompt=PROMPT_TEMPLATE,
        color_filter=HSVFilter(
            hue_lo=120, hue_hi=175,   # blue band in PIL's 0-255 hue
            sat_min=60, val_min=40,   # bright and saturated, not gray or shadowed
            min_frac=0.12,
        ),
        yolo_repo=None,               # no pretrained model -> runs on the vision backend
    ),
}
```

## Step 4: run it

```bash
python -m birdseye --object tarp --backend vision \
    --out out_tarp <lat> <lon> 500
```

If you set a `yolo_repo`, you can leave off `--backend` and it defaults to `yolo`; without
one, it defaults to the `vision` backend.

## A word on accuracy

Adding an object gets it detected. It does **not** make it validated. Swimming pools are the
only object with measured accuracy. Any new object you register is un-benchmarked, so scan a
place you know, open `detected.png`, and sanity-check the rings before trusting a count. If
you tune a new object well, a pull request with your `ObjectSpec` (and any benchmarking notes)
is welcome.
