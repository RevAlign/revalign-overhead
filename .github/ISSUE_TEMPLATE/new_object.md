---
name: New object or benchmark report
about: Propose a new object to detect, or report how well an existing one worked in your area
title: "[object] "
labels: object
---

## Object

What are you detecting? (e.g. "rooftop solar array", "grain silo", "tennis court")

## How did you run it?

- [ ] `vision` backend (`--object-name` or a registered spec, open-vocabulary)
- [ ] `yolo` backend (a bundled pretrained model)

Command you ran:

```bash

```

## What happened (be honest)

- **Region(s) tested:**
- **Imagery / zoom:**
- **Roughly how many were really there vs how many it found:**
- **False positives (what did it circle that was not the object?):**
- **Did the color gate help, or did you leave `color_filter=None`?**

## Attachments

If you can, attach the `detections.csv` and the annotated `detected.png`. A proof image is
worth more than a description.

## If you are proposing a pretrained model

- Hugging Face repo (public, ultralytics-compatible `.pt`):
- What it was trained on (imagery source, zoom, region):
- License of the model and its training deps:
