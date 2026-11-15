# Motion-Aware Video Stabilizer

Offline video stabilization built with Python, OpenCV, and NumPy.

The pipeline detects up to 500 corners per frame, tracks them with Lucas–Kanade optical flow, rejects outliers with RANSAC, and estimates camera translation and rotation. It smooths the reconstructed camera path and applies compensating transforms. Adaptive cropping and geometric recentering conceal exposed borders.

## Setup

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Usage

```sh
video-stabilizer input.mp4 outputs/stabilized.mp4 --comparison outputs/comparison.mp4
```

The comparison shows the original video on the left and stabilized output on the right.

- `--radius 15`: smoothing radius in frames.
- `--zoom 1.05`: minimum crop zoom.
- `--fixed-crop`: disable adaptive cropping and recentering.
- `--comparison PATH`: save an optional side-by-side video.

The command reports input frame rate, processing throughput, tracking failures, and crop statistics.

Adaptive crop zoom anticipates upcoming motion peaks and eases back afterward. Its rate is limited to 0.15 zoom units per second while remaining at or above each frame's border-safe zoom requirement. This trades some field of view for smoother zoom transitions. Geometric crop-center changes are not yet temporally smoothed.

## Tests and benchmark

```sh
pytest
PYTHONPATH=src .venv/bin/python tools/benchmark.py
```

The benchmark generates a seeded 1920×1080 video at 120 FPS with translation shake and a constant pan. It measures translational jitter independently using phase correlation and RMS changes in frame displacement. Generated videos and a JSON report are saved to `outputs/benchmark/`.

The recorded synthetic run reduced jitter by 89.19% and processed 29.0 frames per second with zero tracking failures. The environment was arm64, Python 3.12.10, OpenCV 5.0.0, and NumPy 2.5.4. Full results are in `benchmarks/synthetic-1080p120.json`. Input frame rate and processing throughput are separate measurements; these results do not establish real-time 120 FPS processing or performance on real footage.

## Limitations

- Outputs video only; audio and original metadata are not preserved.
- Uses two offline passes and constant frame rate encoding.
- Models translation and rotation; parallax, rolling shutter, scene cuts, and large foreground motion need additional handling.
- Falls back to identity motion when tracking fails and reports those failures.
- Adaptive cropping can produce large zoom values under strong motion. Crop-center changes can still be abrupt. Recentring is geometric and does not track a subject.
- Fixed cropping reflects exposed borders.
