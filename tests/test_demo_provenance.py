"""Keep the published synthetic comparison tied to its measured fixture."""
import hashlib
import json
from pathlib import Path

import cv2
import pytest


def test_synthetic_comparison_matches_recorded_benchmark():
    root = Path(__file__).resolve().parents[1]
    media = root / "docs"
    manifest = json.loads((media / "synthetic-benchmark.json").read_text())
    report = json.loads((root / "benchmarks" / "synthetic-1080p120.json").read_text())
    for key in ["source_sha256", "output_sha256", "frames", "fps", "settings", "input_jitter", "output_jitter"]:
        assert manifest[key] == report[key]
    reduction = 100 * (1 - report["output_jitter"] / report["input_jitter"])
    assert manifest["jitter_reduction_percent"] == pytest.approx(reduction)
    for filename, key in [("synthetic-benchmark.mp4", "comparison_sha256"), ("synthetic-benchmark.gif", "preview_sha256")]:
        assert hashlib.sha256((media / filename).read_bytes()).hexdigest() == manifest[key]
    capture = cv2.VideoCapture(str(media / "synthetic-benchmark.mp4"))
    try:
        assert capture.get(cv2.CAP_PROP_FPS) == pytest.approx(manifest["playback_fps"])
        frames = 0
        while capture.read()[0]:
            frames += 1
        assert frames == report["frames"] == 120
        assert manifest["playback_fps"] == report["fps"] * manifest["playback_speed"]
        assert manifest["playback_speed"] == .25
    finally:
        capture.release()
