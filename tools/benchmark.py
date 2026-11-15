"""Reproducible synthetic evaluation; not a substitute for real-footage tests."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from video_stabilizer.core import stabilize


def measure_jitter(path):
    """RMS change in displacement, measured independently with phase correlation.

    A constant-velocity pan has zero acceleration, unlike frame displacement.
    This metric measures translation only, not rotation or perceptual quality.
    """
    capture = cv2.VideoCapture(str(path))
    previous = None
    shifts = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = np.float32(gray[h // 5:4 * h // 5, w // 5:4 * w // 5])
            if previous is not None:
                shift, response = cv2.phaseCorrelate(previous, gray)
                if not np.isfinite(shift).all() or response < 0.1:
                    raise ValueError("Phase correlation unreliable; benchmark cannot report a score")
                shifts.append(shift)
            previous = gray
    finally:
        capture.release()
    if len(shifts) < 2:
        raise ValueError("At least three frames required")
    return float(np.sqrt(np.mean(np.sum(np.diff(shifts, axis=0) ** 2, axis=1))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--directory", type=Path, default=Path("outputs/benchmark"))
    args = parser.parse_args()
    if args.frames < 3:
        parser.error("--frames must be at least 3")
    args.directory.mkdir(parents=True, exist_ok=True)
    source = args.directory / "shaky.mp4"
    output = args.directory / "stabilized.mp4"
    rng = np.random.default_rng(2026)
    base = rng.integers(20, 235, (1080, 1920, 3), dtype=np.uint8)
    base = cv2.GaussianBlur(base, (5, 5), 0)
    for _ in range(600):
        center = tuple(int(v) for v in rng.integers([30, 30], [1890, 1050]))
        color = tuple(int(v) for v in rng.integers(0, 256, 3))
        cv2.circle(base, center, int(rng.integers(3, 14)), color, -1)
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 120, (1920, 1080))
    if not writer.isOpened():
        raise RuntimeError("Cannot create benchmark input")
    try:
        for i in range(args.frames):
            # Intentional slow pan plus independently sampled camera shake.
            dx = i * 0.25 + rng.normal(0, 5)
            dy = rng.normal(0, 4)
            frame = cv2.warpAffine(base, np.float32([[1, 0, dx], [0, 1, dy]]), (1920, 1080), borderMode=cv2.BORDER_REFLECT)
            writer.write(frame)
    finally:
        writer.release()
    report = stabilize(source, output, radius=15)
    before, after = measure_jitter(source), measure_jitter(output)
    report.update({"evaluation": "synthetic translation shake with constant pan; seed=2026",
                   "settings": {"radius": 15, "minimum_zoom": 1.05, "maximum_zoom": 1.25},
                   "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                   "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                   "metric": "RMS inter-frame displacement change (pixels/frame^2), phase correlation",
                   "input_jitter": before, "output_jitter": after,
                   "jitter_reduction_percent": 100 * (1 - after / before),
                   "real_time_120fps_verified": report["processing_fps"] >= 120,
                   "limitations": "Synthetic translation only; excludes rotation, parallax, scene cuts, audio and real-world quality."})
    (args.directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
