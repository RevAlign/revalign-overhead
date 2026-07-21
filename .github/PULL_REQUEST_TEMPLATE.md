<!-- Thanks for contributing to birdseye. Keep it honest: say what you validated and what you did not. -->

## What this changes

<!-- One or two sentences. -->

## Type

- [ ] New object / detector
- [ ] New pretrained model (`yolo_repo`)
- [ ] Bug fix
- [ ] Docs
- [ ] Other

## For detector or model changes: what did you validate?

<!-- Required if you touched detection. Be specific and honest. -->

- **Object:**
- **Region(s) tested:**
- **Imagery / zoom:**
- **Recall you observed (roughly):**
- **False-positive behavior:**
- **What is still UN-benchmarked:**

Attach the `detections.csv` and the annotated `detected.png` from a real run if you can.

## Checklist

- [ ] `python -m birdseye --help` works
- [ ] `pytest -q` passes (offline, no network, no keys)
- [ ] No em dashes in code, comments, or docs
- [ ] Any new object is documented honestly (validated vs un-benchmarked)
- [ ] No secrets, keys, or private data added
