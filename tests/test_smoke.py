"""Offline smoke tests for revalign_overhead.

These run with no network, no API keys, and no model download. They exercise the
pure functions (tile math, the object registry, spec resolution) and confirm the
CLI parser builds. Everything that would touch the network (build_canvas, detect,
the backends) is intentionally left out.
"""
import importlib
import math
from types import SimpleNamespace

import pytest

import revalign_overhead

# Import the detect module explicitly. The package re-exports a `detect` function,
# which shadows the `detect` submodule as an attribute, so importlib is the robust
# way to get the module object itself.
gt = importlib.import_module("revalign_overhead.detect")


def test_package_imports_and_exposes_public_api():
    assert revalign_overhead.__version__
    for name in ("detect", "build_canvas", "ObjectSpec", "HSVFilter", "OBJECTS"):
        assert hasattr(revalign_overhead, name)


def test_pool_is_registered_and_well_formed():
    assert "pool" in gt.OBJECTS
    pool = gt.OBJECTS["pool"]
    assert isinstance(pool, gt.ObjectSpec)
    assert pool.size_m > 0
    # Pools ship with a bundled YOLO model and a blue-water color gate.
    assert pool.yolo_repo
    assert isinstance(pool.color_filter, gt.HSVFilter)


def test_meters_per_px_is_sane():
    # At the equator, zoom 0, one 256px tile spans the world; the classic constant.
    assert gt.meters_per_px(0.0, 0) == pytest.approx(156543.03392, rel=1e-6)
    # Always positive, and each extra zoom level halves the ground resolution.
    assert gt.meters_per_px(33.54, 19) > 0
    assert gt.meters_per_px(33.54, 19) == pytest.approx(
        gt.meters_per_px(33.54, 18) / 2.0, rel=1e-9
    )
    # Toward the poles a pixel covers less ground than at the equator (cos(lat)).
    assert gt.meters_per_px(60.0, 19) < gt.meters_per_px(0.0, 19)


def test_deg2tile_is_sane():
    # Null Island at zoom 1 sits at the center of a 2x2 tile grid.
    x, y = gt.deg2tile(0.0, 0.0, 1)
    assert x == pytest.approx(1.0)
    assert y == pytest.approx(1.0)
    # Any real coordinate maps inside the [0, 2**z] tile grid.
    z = 19
    n = 2 ** z
    tx, ty = gt.deg2tile(33.54, -111.95, z)
    assert 0.0 <= tx <= n
    assert 0.0 <= ty <= n
    assert math.isfinite(tx) and math.isfinite(ty)


def test_spec_for_resolves_registered_object():
    args = SimpleNamespace(object="pool", object_name=None, object_size=None, prompt=None)
    spec = gt.spec_for(args)
    assert spec is gt.OBJECTS["pool"]


def test_spec_for_builds_ad_hoc_object():
    args = SimpleNamespace(
        object="pool",  # ignored when object_name is set
        object_name="round backyard trampoline",
        object_size=4.0,
        prompt=None,
    )
    spec = gt.spec_for(args)
    assert isinstance(spec, gt.ObjectSpec)
    assert spec.name == "round backyard trampoline"
    assert spec.size_m == 4.0
    assert spec.yolo_repo is None  # ad-hoc objects have no bundled model


def test_spec_for_rejects_unknown_object():
    args = SimpleNamespace(object="nope", object_name=None, object_size=None, prompt=None)
    with pytest.raises(SystemExit):
        gt.spec_for(args)


def test_cli_parser_builds_without_network():
    # --help builds the argparse parser, prints usage, and exits before any
    # network work. A clean SystemExit(0) proves the CLI wiring is intact.
    with pytest.raises(SystemExit) as exc:
        gt.main(["--help"])
    assert exc.value.code == 0
