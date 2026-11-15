"""Generate a shareable before/after demo with reproducible synthetic motion."""
import argparse
import json
from pathlib import Path
import subprocess

import cv2
import imageio_ffmpeg
import numpy as np

from video_stabilizer.core import stabilize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("outputs/demo"))
    parser.add_argument("--preview", type=Path, default=Path("docs/demo.gif"))
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    args.preview.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(2026)
    height, width = 540, 960
    # A scene with stable corners and reference lines makes camera shake visible.
    scene = np.full((height + 160, width + 240, 3), (32, 26, 20), np.uint8)
    for y in range(0, scene.shape[0], 40):
        cv2.line(scene, (0, y), (scene.shape[1], y), (55, 48, 38), 1)
    for x in range(0, scene.shape[1], 40):
        cv2.line(scene, (x, 0), (x, scene.shape[0]), (55, 48, 38), 1)
    for _ in range(200):
        x, y = rng.integers([10, 10], [scene.shape[1] - 20, scene.shape[0] - 20])
        color = tuple(int(value) for value in rng.integers(65, 200, 3))
        cv2.rectangle(scene, (x, y), (x + 10, y + 10), color, -1)
    cv2.rectangle(scene, (250, 200), (820, 450), (70, 160, 225), 3)
    cv2.circle(scene, (535, 325), 90, (200, 200, 90), 3)
    cv2.line(scene, (535, 210), (535, 440), (235, 235, 235), 2)
    cv2.line(scene, (420, 325), (650, 325), (235, 235, 235), 2)
    cv2.putText(scene, "SYNTHETIC MOTION TEST", (280, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (230, 230, 230), 2)
    source = args.directory / "shaky.mp4"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 30, (width, height))
    if not writer.isOpened():
        raise RuntimeError("Cannot create demo input")
    try:
        for i in range(120):
            # Slow intended pan plus deterministic translation and rotation shake.
            crop = scene[80:80 + height, 100 + i // 4:100 + i // 4 + width]
            transform = cv2.getRotationMatrix2D((width / 2, height / 2), rng.normal(0, 0.4), 1)
            transform[:, 2] += rng.normal(0, 4, 2)
            writer.write(cv2.warpAffine(crop, transform, (width, height), borderMode=cv2.BORDER_REFLECT))
    finally:
        writer.release()
    comparison = args.directory / "comparison.mp4"
    report = stabilize(source, args.directory / "stabilized.mp4", comparison=comparison)
    # Add fixed labels outside the moving scene for the preview.
    labeled = args.directory / "labeled.mp4"
    capture = cv2.VideoCapture(str(comparison))
    writer = cv2.VideoWriter(str(labeled), cv2.VideoWriter_fourcc(*"mp4v"), 30, (width * 2, height + 60))
    if not writer.isOpened():
        capture.release()
        raise RuntimeError("Cannot create labeled demo")
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            canvas = np.zeros((height + 60, width * 2, 3), np.uint8)
            canvas[60:] = frame
            for x, text in [(20, "ORIGINAL / SYNTHETIC SHAKE"), (width + 20, "STABILIZED")]:
                cv2.putText(canvas, text, (x, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (240, 240, 240), 2)
            writer.write(canvas)
    finally:
        writer.release()
        capture.release()
    filters = "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse=dither=bayer:bayer_scale=3"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-i", str(labeled),
                    "-filter_complex", filters, "-loop", "0", str(args.preview)], check=True)
    report["fixture"] = "Synthetic 4-second clip, seed 2026; translation and rotation shake with slow pan"
    (args.directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
