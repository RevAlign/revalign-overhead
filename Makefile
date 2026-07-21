.PHONY: help install install-yolo test demo clean

help:
	@echo "make install       editable core install (open-vocab vision backend)"
	@echo "make install-yolo  core + free local YOLO pool detector (pulls AGPL-3.0 deps)"
	@echo "make test          run the offline smoke tests"
	@echo "make demo          run the validated pool scan over Paradise Valley, AZ (\$$0)"
	@echo "make clean         remove build and output artifacts"

install:
	pip install -e .

install-yolo:
	pip install -e ".[yolo]"

test:
	python -m pytest -q

# One-shot free demo: installs the local pool detector and scans a real neighborhood.
# Writes detections.csv + the annotated detected.png proof image into ./out_demo.
# $0, no API key, imagery is free. First run downloads the pool weights once.
demo:
	pip install -e ".[yolo]"
	python -m birdseye --object pool --backend yolo --out out_demo 33.5400 -111.9500 510
	@echo ""
	@echo "Done. Open out_demo/detected.png (proof image) and out_demo/detections.csv"

clean:
	rm -rf out out_* build dist *.egg-info .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
