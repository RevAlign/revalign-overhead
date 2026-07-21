#!/usr/bin/env python3
"""
birdseye: find any object in overhead satellite imagery and get back a
georeferenced, spreadsheet-ready list.

Point it at a location + radius, tell it what to look for, and it will:

    center/bbox -> free Esri satellite tiles -> stitch one big canvas
    -> detect (local YOLO model | open-vocabulary vision LLM)
    -> cross-window dedup -> optional color precision-filter
    -> detections.csv (lat, lon, confidence, Google Maps link) + an annotated proof PNG.

Two detection backends:

    yolo    A local YOLO model. $0 per scan, runs offline once weights are cached.
            Only for objects that have a pretrained model (swimming pools ship out
            of the box). Needs `ultralytics` + `huggingface_hub` (pip extra: [yolo]).
            Note: ultralytics and the pretrained pool weights are AGPL-3.0.

    vision  An open-vocabulary vision LLM (Anthropic Claude by default, OpenAI
            optional; `claude` is accepted as an alias for this backend). Works for
            ANY object you can describe in a sentence. Costs a few cents per scan.

Why it works on small objects: the scan is sliced into fixed-ground-size chunks so
the target renders at a roughly constant pixel size everywhere on Earth (Web
Mercator meters-per-pixel varies with latitude). Big single-image inference misses
small things; native-resolution windows don't.

Quickstart:

    pip install -e ".[yolo]"                      # core + the free local pool detector
    python -m birdseye --object pool 33.5400 -111.9500 510

Describe your own object (no code, no model needed, uses the vision backend):

    export ANTHROPIC_API_KEY=...
    python -m birdseye --backend vision \\
        --object-name "center-pivot irrigation circle" --object-size 400 \\
        41.88 -101.72 3000

Add a reusable object: register an ObjectSpec in OBJECTS below.

Imagery: Esri World Imagery tiles are free and need no API key. They cap out around
zoom 19 in many areas (the tool auto-falls-back a zoom level when a tile is missing).
For higher-resolution imagery, swap the TILE_URL for a keyed provider.

License: Apache-2.0.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

from PIL import Image, ImageDraw, ImageStat

# --------------------------------------------------------------------------- config
TILE_URL = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
TILE = 256                 # provider tile size, px
CHUNK_OVERLAP = 0.18       # vision-chunk overlap so objects on a boundary aren't split
MAX_VISION_WORKERS = 4     # concurrent LLM calls (raise if your rate limit allows)
DEDUP_M = 8                # merge two detections closer than this many meters

# Anthropic / OpenAI models for the `claude` backend.
ANTHROPIC_MODEL = os.environ.get("GT_ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENAI_MODEL = os.environ.get("GT_OPENAI_MODEL", "gpt-4o-mini")

# YOLO backend: sliced (SAHI-style) native-resolution inference.
YOLO_WIN, YOLO_WIN_OVERLAP, YOLO_CONF = 512, 0.25, 0.12
YOLO_CONF_FLOOR = 0.20     # confirmed-detection cutoff on YOLO's confidence scale
_YOLO_CACHE: dict = {}


# --------------------------------------------------------------------------- object specs
@dataclass
class HSVFilter:
    """A cheap, deterministic color gate applied AFTER detection to cut false
    positives. Counts what fraction of a small patch around a detection falls in an
    HSV window; a detection is only 'confirmed' if that fraction clears `min_frac`.
    PIL HSV channels are 0-255. Great for strongly-colored objects (pool water,
    blue tarps); leave None for objects without a reliable signature color."""
    hue_lo: int
    hue_hi: int
    sat_min: int
    val_min: int
    min_frac: float = 0.10
    patch_r: int = 16


@dataclass
class ObjectSpec:
    """Everything the pipeline needs to look for one kind of object."""
    name: str                                  # human name, injected into the prompt
    size_m: float                              # typical real-world width in meters
    prompt: str                                # vision-LLM instruction (see PROMPT_TEMPLATE)
    color_filter: Optional[HSVFilter] = None   # optional precision gate
    yolo_repo: Optional[str] = None            # HF repo of a pretrained YOLO model, if any
    yolo_weights: str = "model.pt"             # weights filename inside that repo


# The vision prompt is templated: {name}, {wpx}, {hpx}, {mpp}, {obj_px} are filled in
# per chunk. Detections come back as STRICT JSON so parsing never depends on prose.
PROMPT_TEMPLATE = (
    "This is a top-down aerial satellite image, {wpx}x{hpx} px at ~{mpp:.2f} m/px. "
    "A {name} is roughly {obj_px} px wide at this scale. "
    "Detect every {name} visible in the image. Be precise about the center point. "
    'Return STRICT JSON: {{"detections":[{{"x":<int>,"y":<int>,'
    '"confidence":<0..1>,"note":"<short reason>"}}]}} '
    "where x,y is each object's CENTER in THIS image (top-left origin, pixels). "
    "Return an empty list if there are none. Output ONLY the JSON."
)

OBJECTS: dict[str, ObjectSpec] = {
    # Swimming pools: validated end-to-end. Ships with a free local YOLO model AND a
    # blue-water color gate, so both backends work well.
    "pool": ObjectSpec(
        name="backyard swimming pool (a blue/teal water rectangle or freeform shape)",
        size_m=7.0,
        prompt=(
            "This is a top-down aerial satellite image, {wpx}x{hpx} px at ~{mpp:.2f} m/px "
            "(a residential area; a backyard pool is ~{obj_px} px wide). Detect every "
            "SWIMMING POOL -- a blue/teal water rectangle or freeform shape in a yard. "
            "IGNORE roofs, shadows, vegetation, ponds, driveways, trampolines. "
            'Return STRICT JSON {{"detections":[{{"x":<int>,"y":<int>,'
            '"confidence":<0..1>,"note":"<why>"}}]}} where x,y is each pool CENTER in '
            "THIS image (top-left origin). Empty list if none. Output ONLY the JSON."
        ),
        color_filter=HSVFilter(hue_lo=115, hue_hi=190, sat_min=45, val_min=35,
                               min_frac=0.10, patch_r=16),
        yolo_repo="mozilla-ai/swimming-pool-detector",
    ),
    # Solar arrays: works via the open-vocab `claude` backend. No pretrained YOLO
    # model bundled and no reliable single color, so recall/precision are un-benchmarked
    # here -- treat as a starting point, not a validated detector. Contributions welcome.
    "solar": ObjectSpec(
        name="rooftop or ground-mount solar panel array (a dark blue/black rectangular grid)",
        size_m=6.0,
        prompt=PROMPT_TEMPLATE,
        color_filter=None,
        yolo_repo=None,
    ),
}


def spec_for(args) -> ObjectSpec:
    """Resolve the ObjectSpec to run: an ad-hoc one from --object-name/--object-size,
    otherwise a registered object by key."""
    if args.object_name:
        return ObjectSpec(
            name=args.object_name,
            size_m=args.object_size or 10.0,
            prompt=args.prompt or PROMPT_TEMPLATE,
            color_filter=None,
            yolo_repo=None,
        )
    if args.object not in OBJECTS:
        sys.exit(f"unknown --object '{args.object}'. Known: {', '.join(OBJECTS)}. "
                 f"Or describe one with --object-name/--object-size.")
    return OBJECTS[args.object]


# --------------------------------------------------------------------------- tile math
def meters_per_px(lat: float, z: int) -> float:
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** z)


def deg2tile(lat: float, lon: float, z: int) -> tuple[float, float]:
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def _is_placeholder(im: Image.Image) -> bool:
    """A 'map data not yet available' tile is a neutral light-gray card with a little
    dark text (low variance). Real imagery is tan/green (non-neutral) and textured."""
    r, g, b = ImageStat.Stat(im).mean
    neutral = max(r, g, b) - min(r, g, b) < 10           # gray, not tan/green ground
    light = (r + g + b) / 3 > 175
    flat = ImageStat.Stat(im.convert("L")).stddev[0] < 24
    return neutral and light and flat


def fetch_tile(z: int, x: int, y: int) -> tuple[Image.Image, bool]:
    req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": UA})
    for _ in range(3):
        try:
            data = urllib.request.urlopen(req, timeout=30).read()
            im = Image.open(io.BytesIO(data)).convert("RGB")
            return im, not _is_placeholder(im)
        except Exception:                                 # noqa: BLE001 - retry any fetch error
            time.sleep(0.5)
    return Image.new("RGB", (TILE, TILE), (40, 40, 40)), False


def build_canvas(lat: float, lon: float, size_m: float, z: int):
    """Stitch every tile covering a `size_m` square centered on lat/lon into one image.
    Auto-falls-back a zoom level if the provider hasn't got high-res imagery here."""
    m = meters_per_px(lat, z)
    half_tiles = max(1, int(math.ceil((size_m / m / TILE) / 2)))
    xc, yc = deg2tile(lat, lon, z)
    x0, y0 = int(xc) - half_tiles, int(yc) - half_tiles
    nx = ny = half_tiles * 2 + 1
    canvas = Image.new("RGB", (nx * TILE, ny * TILE))
    coords = [(dx, dy) for dx in range(nx) for dy in range(ny)]
    avail = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_tile, z, x0 + dx, y0 + dy): (dx, dy) for dx, dy in coords}
        for fut in as_completed(futs):
            dx, dy = futs[fut]
            im, ok = fut.result()
            avail += ok
            canvas.paste(im, (dx * TILE, dy * TILE))
    if avail / len(coords) < 0.5 and z > 16:
        print(f"  z{z}: {len(coords) - avail}/{len(coords)} tiles unavailable "
              f"-> falling back to z{z - 1}")
        return build_canvas(lat, lon, size_m, z - 1)
    return canvas, {"z": z, "x0": x0, "y0": y0, "tile": TILE, "mpp": m,
                    "w": nx * TILE, "h": ny * TILE, "n_tiles": nx * ny, "tiles_avail": avail}


def canvas_to_latlon(px: float, py: float, g: dict) -> tuple[float, float]:
    n = 2 ** g["z"]
    gx, gy = g["x0"] * g["tile"] + px, g["y0"] * g["tile"] + py
    lon = gx / (g["tile"] * n) * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * gy / (g["tile"] * n)))))
    return lat, lon


# --------------------------------------------------------------------------- vision (LLM) backend
def _b64(im: Image.Image) -> str:
    b = io.BytesIO()
    im.save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def _http_post(url: str, headers: dict, body: dict):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def _parse_detections(txt: str) -> list:
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(0)).get("detections", [])
    except Exception:                                     # noqa: BLE001
        return []


def vision_detect(im: Image.Image, mpp_val: float, spec: ObjectSpec, provider: str) -> list:
    w, h = im.size
    prompt = spec.prompt.format(name=spec.name, wpx=w, hpx=h, mpp=mpp_val,
                                obj_px=max(1, round(spec.size_m / mpp_val)))
    if provider == "openai":
        st, r = _http_post(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
             "Content-Type": "application/json"},
            {"model": OPENAI_MODEL, "max_tokens": 1500,
             "response_format": {"type": "json_object"},
             "messages": [{"role": "user", "content": [
                 {"type": "text", "text": prompt},
                 {"type": "image_url", "image_url":
                     {"url": f"data:image/png;base64,{_b64(im)}", "detail": "high"}}]}]})
        return _parse_detections(r["choices"][0]["message"]["content"]) if st == 200 else []
    st, r = _http_post(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
         "anthropic-version": "2023-06-01", "content-type": "application/json"},
        {"model": ANTHROPIC_MODEL, "max_tokens": 1500,
         "messages": [{"role": "user", "content": [
             {"type": "text", "text": prompt},
             {"type": "image", "source": {"type": "base64",
              "media_type": "image/png", "data": _b64(im)}}]}]})
    return _parse_detections(r["content"][0]["text"]) if st == 200 else []


# --------------------------------------------------------------------------- YOLO backend (local, $0)
def _load_yolo(spec: ObjectSpec):
    if spec.yolo_repo in _YOLO_CACHE:
        return _YOLO_CACHE[spec.yolo_repo]
    import glob
    from ultralytics import YOLO                          # lazy: only when backend=yolo
    stem = spec.yolo_repo.split("/")[-1]
    hits = [p for p in glob.glob(os.path.expanduser("~/.cache/huggingface/**/*.pt"),
                                 recursive=True) if stem.split("-")[0] in p]
    if hits:
        weights = hits[0]
    else:                                                 # first run: pull weights once
        from huggingface_hub import hf_hub_download
        weights = hf_hub_download(spec.yolo_repo, spec.yolo_weights,
                                  token=os.environ.get("HUGGINGFACE_API_KEY"))
    model = YOLO(weights)
    _YOLO_CACHE[spec.yolo_repo] = model
    return model


def yolo_detect_canvas(canvas: Image.Image, spec: ObjectSpec):
    """Sliced (SAHI-style) inference over the whole canvas. Native-resolution windows
    keep small objects detectable that one downscaled pass would miss. Returns
    [(cx, cy, conf, 'yolo'), ...] in canvas pixels."""
    model = _load_yolo(spec)
    W, H = canvas.size
    step = int(YOLO_WIN * (1 - YOLO_WIN_OVERLAP))
    dets, windows = [], 0
    for y in range(0, max(1, H - 1), step):
        for x in range(0, max(1, W - 1), step):
            sub = canvas.crop((x, y, min(x + YOLO_WIN, W), min(y + YOLO_WIN, H)))
            windows += 1
            for b in model.predict(sub, imgsz=YOLO_WIN, conf=YOLO_CONF, verbose=False)[0].boxes:
                x1, y1, x2, y2 = b.xyxy[0].tolist()
                cx, cy = x + (x1 + x2) / 2, y + (y1 + y2) / 2
                if 0 <= cx < W and 0 <= cy < H:
                    dets.append((cx, cy, float(b.conf.item()), "yolo"))
    return dets, windows


# --------------------------------------------------------------------------- precision filter
def color_score(canvas: Image.Image, px: float, py: float, f: HSVFilter) -> float:
    """Fraction of a patch around (px, py) that falls inside the HSV window."""
    r = f.patch_r
    patch = canvas.crop((int(px - r), int(py - r), int(px + r), int(py + r))).convert("HSV")
    data = list(patch.getdata())
    if not data:
        return 0.0
    hit = sum(1 for H, S, V in data
              if f.hue_lo <= H <= f.hue_hi and S >= f.sat_min and V >= f.val_min)
    return hit / len(data)


# --------------------------------------------------------------------------- pipeline
def detect(lat: float, lon: float, size_m: float, z: int, spec: ObjectSpec,
           backend: str = "yolo", provider: str = "anthropic",
           outdir: str = "out") -> list:
    if backend == "claude":                                   # back-compat alias
        backend = "vision"
    os.makedirs(outdir, exist_ok=True)
    canvas, g = build_canvas(lat, lon, size_m, z)
    canvas.save(f"{outdir}/canvas.png")

    if backend == "yolo":
        if not spec.yolo_repo:
            sys.exit(f"object '{spec.name}' has no bundled YOLO model. "
                     f"Run with --backend vision to use the open-vocabulary detector.")
        raw, calls = yolo_detect_canvas(canvas, spec)
        conf_floor, unit_cost = YOLO_CONF_FLOOR, 0.0
        print(f"canvas {g['w']}x{g['h']} ({g['n_tiles']} tiles, {g['mpp']:.3f} m/px) "
              f"-> YOLO sliced over {calls} windows (local, $0)")
    else:
        chunk_px = max(192, round((spec.size_m * 16) / g["mpp"]))   # ~16 objects across a chunk
        step = int(chunk_px * (1 - CHUNK_OVERLAP))
        boxes = [(x, y) for y in range(0, g["h"] - 1, step) for x in range(0, g["w"] - 1, step)]
        print(f"canvas {g['w']}x{g['h']} ({g['n_tiles']} tiles, {g['mpp']:.3f} m/px) "
              f"-> {len(boxes)} chunks of {chunk_px}px via {provider}")

        def work(bx):
            x, y = bx
            sub = canvas.crop((x, y, min(x + chunk_px, g["w"]), min(y + chunk_px, g["h"])))
            out = []
            for d in vision_detect(sub, g["mpp"], spec, provider):
                try:
                    cx, cy = x + int(d["x"]), y + int(d["y"])
                except Exception:                          # noqa: BLE001
                    continue
                if 0 <= cx < g["w"] and 0 <= cy < g["h"]:
                    out.append((cx, cy, float(d.get("confidence", 0.5)), d.get("note", "")))
            return out

        raw, calls = [], 0
        with ThreadPoolExecutor(max_workers=MAX_VISION_WORKERS) as ex:
            for fut in as_completed([ex.submit(work, b) for b in boxes]):
                raw.extend(fut.result())
                calls += 1
        conf_floor = 0.5
        unit_cost = 0.006 if provider == "anthropic" else 0.001

    # cross-window dedup (keep the highest-confidence of any cluster within DEDUP_M)
    dpx = DEDUP_M / g["mpp"]
    merged = []
    for cx, cy, conf, note in sorted(raw, key=lambda r: -r[2]):
        if all(math.hypot(cx - m[0], cy - m[1]) > dpx for m in merged):
            merged.append((cx, cy, conf, note))

    # optional color precision-filter + georeference
    rows = []
    for cx, cy, conf, note in merged:
        cs = color_score(canvas, cx, cy, spec.color_filter) if spec.color_filter else None
        lat_d, lon_d = canvas_to_latlon(cx, cy, g)
        if spec.color_filter:
            confirmed = cs >= spec.color_filter.min_frac and conf >= conf_floor
        else:
            confirmed = conf >= conf_floor
        rows.append({
            "lat": round(lat_d, 6), "lon": round(lon_d, 6),
            "status": "confirmed" if confirmed else "tentative",
            "model_conf": round(conf, 2),
            "color_score": round(cs, 3) if cs is not None else "",
            "gmaps": f"https://www.google.com/maps/search/?api=1&query={lat_d:.6f},{lon_d:.6f}",
            "note": note, "_px": (cx, cy),
        })

    # annotate a proof image: green = confirmed, amber = tentative
    d = ImageDraw.Draw(canvas)
    for r in rows:
        cx, cy = r.pop("_px")
        col = (0, 255, 0) if r["status"] == "confirmed" else (255, 200, 0)
        d.ellipse([cx - 22, cy - 22, cx + 22, cy + 22], outline=col, width=5)
    canvas.save(f"{outdir}/detected.png")

    with open(f"{outdir}/detections.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["lat", "lon", "status", "model_conf",
                                          "color_score", "gmaps", "note"])
        w.writeheader()
        w.writerows(rows)

    conf_n = sum(1 for r in rows if r["status"] == "confirmed")
    est = calls * unit_cost
    print(f"\n{len(rows)} detections -> {conf_n} confirmed, {len(rows) - conf_n} tentative")
    print(f"backend={backend}  units={calls}  est cost ~${est:.2f}  (Esri tiles free)")
    print(f"out: {outdir}/detections.csv  ·  canvas.png  ·  detected.png")
    return rows


# --------------------------------------------------------------------------- CLI
def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(
        prog="birdseye",
        description="Detect any object in overhead satellite imagery -> georeferenced CSV.")
    p.add_argument("lat", type=float, help="center latitude (decimal degrees)")
    p.add_argument("lon", type=float, help="center longitude (decimal degrees)")
    p.add_argument("size_m", type=float, help="square scan size, meters (e.g. 510)")
    p.add_argument("zoom", type=int, nargs="?", default=19, help="tile zoom (default 19)")
    p.add_argument("--object", default="pool",
                   help=f"registered object: {', '.join(OBJECTS)} (default: pool)")
    p.add_argument("--object-name", default=None,
                   help="describe an ad-hoc object instead of using --object (claude backend)")
    p.add_argument("--object-size", type=float, default=None,
                   help="ad-hoc object's typical real-world width in meters")
    p.add_argument("--prompt", default=None, help="override the vision prompt template")
    p.add_argument("--backend", choices=["yolo", "vision", "claude"], default=None,
                   help="detector backend: yolo | vision ('claude' is an alias for vision) "
                        "(default: yolo if the object has a model, else vision)")
    p.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic",
                   help="vision LLM provider for the vision backend (default: anthropic)")
    p.add_argument("--out", default="out", help="output directory (default: ./out)")
    args = p.parse_args(argv)

    spec = spec_for(args)
    backend = args.backend or ("yolo" if spec.yolo_repo else "vision")
    detect(args.lat, args.lon, args.size_m, args.zoom, spec,
           backend=backend, provider=args.provider, outdir=args.out)


if __name__ == "__main__":
    main()
