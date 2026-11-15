"""Track features, smooth the camera path, and render corrected frames."""
from pathlib import Path
import time

import cv2
import numpy as np


def estimate_motion(previous, current):
    points = cv2.goodFeaturesToTrack(previous, 500, 0.01, 10)
    if points is None or len(points) < 6:
        return np.eye(3), False
    tracked, status, _ = cv2.calcOpticalFlowPyrLK(previous, current, points, None)
    if tracked is None:
        return np.eye(3), False
    valid = status.ravel().astype(bool)
    if valid.sum() < 6:
        return np.eye(3), False
    affine, inliers = cv2.estimateAffinePartial2D(
        points[valid], tracked[valid], method=cv2.RANSAC,
        ransacReprojThreshold=3.0,
    )
    if affine is None or inliers.sum() < 6 or not np.isfinite(affine).all():
        return np.eye(3), False
    # Remove estimated scale so noisy zoom estimates do not accumulate.
    angle = np.arctan2(affine[1, 0], affine[0, 0])
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s, affine[0, 2]], [s, c, affine[1, 2]], [0, 0, 1]]), True


def smooth_path(path, radius):
    if radius < 0:
        raise ValueError("Smoothing radius must be nonnegative")
    if not radius:
        return path.copy()
    padded = np.pad(path, ((radius, radius), (0, 0)), mode="edge")
    kernel = np.ones(2 * radius + 1) / (2 * radius + 1)
    return np.column_stack([np.convolve(padded[:, i], kernel, mode="valid") for i in range(path.shape[1])])


def adaptive_crop(correction, width, height, minimum_zoom=1.05):
    """Fit an output-aspect rectangle inside the transformed source footprint.

    Inverse-mapped corners must lie inside a one-pixel interpolation margin.
    Recenter by 10% of the transformed image center displacement, preserving
    most of the stabilization correction. This is geometric, not subject tracking.
    """
    center = np.array([(width - 1) / 2, (height - 1) / 2])
    half = center.copy()
    inverse = np.linalg.inv(correction)
    source_center = (correction @ np.r_[center, 1])[:2]
    crop_center = center + 0.1 * (source_center - center)

    def inside(candidate, scale):
        corners = candidate + np.array([[-1, -1], [-1, 1], [1, -1], [1, 1]]) * half * scale
        mapped = np.column_stack([corners, np.ones(4)]) @ inverse.T
        return bool(((mapped[:, :2] >= 1) & (mapped[:, :2] <= [width - 2, height - 2])).all())

    # Extreme displacements may put the nominal crop center outside the image.
    if not inside(crop_center, 0):
        crop_center = source_center
    low, high = 0., 1. / minimum_zoom
    for _ in range(32):
        mid = (low + high) / 2
        if inside(crop_center, mid):
            low = mid
        else:
            high = mid
    if low <= 1e-6:
        raise ValueError("Motion is too large to compute a usable crop")
    scale = 1. / low
    crop = np.array([[scale, 0, center[0] - scale * crop_center[0]],
                     [0, scale, center[1] - scale * crop_center[1]], [0, 0, 1]])
    return crop @ correction, scale


def smooth_crop_zooms(required, max_step=0.005):
    """Anticipate crop peaks without ever zooming below the safe requirement.

    Forward and backward envelopes limit zoom changes in both directions.
    Unlike averaging, this preserves the border coverage of every frame.
    """
    if not np.isfinite(max_step) or max_step <= 0:
        raise ValueError("Maximum zoom step must be positive and finite")
    result = np.asarray(required, dtype=float).copy()
    if result.ndim != 1 or not np.isfinite(result).all() or (result < 1).any():
        raise ValueError("Required zooms must be a finite vector of values at least 1")
    for i in range(1, len(result)):
        result[i] = max(result[i], result[i - 1] - max_step)
    for i in range(len(result) - 2, -1, -1):
        result[i] = max(result[i], result[i + 1] - max_step)
    return result


def stabilize(source, destination, radius=15, zoom=1.05, comparison=None, adaptive=True):
    source, destination = Path(source), Path(destination)
    paths = [source.resolve(), destination.resolve()]
    if comparison:
        paths.append(Path(comparison).resolve())
    if len(set(paths)) != len(paths):
        raise ValueError("Input, output, and comparison paths must be different")
    if radius < 0 or not np.isfinite(zoom) or zoom < 1:
        raise ValueError("Radius must be nonnegative and zoom must be finite and at least 1")
    started = time.perf_counter()
    capture = cv2.VideoCapture(str(source))
    writers = []
    try:
        ok, first = capture.read()
        if not ok:
            raise ValueError(f"Cannot read video: {source}")
        height, width = first.shape[:2]
        if min(width, height) < 4:
            raise ValueError("Video dimensions must be at least 4 pixels")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not np.isfinite(fps) or fps <= 0:
            raise ValueError("Video does not report a valid frame rate")
        previous = cv2.cvtColor(first, cv2.COLOR_BGR2GRAY)
        poses = [np.eye(3)]
        failures = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            current = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            motion, reliable = estimate_motion(previous, current)
            poses.append(motion @ poses[-1])
            failures += not reliable
            previous = current
        path = np.array([[p[0, 2], p[1, 2], np.arctan2(p[1, 0], p[0, 0])] for p in poses])
        path[:, 2] = np.unwrap(path[:, 2])
        smoothed = smooth_path(path, radius)
        capture.release()
        capture = cv2.VideoCapture(str(source))
        for filename, size in [(destination, (width, height))] + ([(Path(comparison), (width * 2, height))] if comparison else []):
            filename.parent.mkdir(parents=True, exist_ok=True)
            writer = cv2.VideoWriter(str(filename), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
            writers.append(writer)
            if not writer.isOpened():
                raise ValueError(f"Cannot create video: {filename}")
        zoom_matrix = np.vstack([cv2.getRotationMatrix2D((width / 2, height / 2), 0, zoom), [0, 0, 1]])
        corrections = []
        crop_zooms = []
        for i, pose in enumerate(poses):
            x, y, angle = smoothed[i]
            c, s = np.cos(angle), np.sin(angle)
            target = np.array([[c, -s, x], [s, c, y], [0, 0, 1]])
            correction = target @ np.linalg.inv(pose)
            if adaptive:
                correction, crop_zoom = adaptive_crop(correction, width, height, zoom)
            else:
                correction, crop_zoom = zoom_matrix @ correction, zoom
            crop_zooms.append(crop_zoom)
            corrections.append(correction)
        # Express the limit per second so 30 and 120 FPS clips behave alike.
        rendered_zooms = smooth_crop_zooms(crop_zooms, max_step=0.15 / fps) if adaptive else np.array(crop_zooms)
        center = np.array([(width - 1) / 2, (height - 1) / 2])
        for correction, required, applied in zip(corrections, crop_zooms, rendered_zooms):
            ok, frame = capture.read()
            if not ok:
                raise ValueError("Input changed or could not be decoded on the rendering pass")
            extra_zoom = applied / required
            envelope = np.array([[extra_zoom, 0, center[0] * (1 - extra_zoom)],
                                 [0, extra_zoom, center[1] * (1 - extra_zoom)], [0, 0, 1]])
            correction = envelope @ correction
            result = cv2.warpAffine(frame, correction[:2], (width, height), borderMode=cv2.BORDER_REFLECT)
            writers[0].write(result)
            if comparison:
                writers[1].write(np.hstack([frame, result]))
        elapsed = time.perf_counter() - started
        return {"frames": len(poses), "fps": fps, "width": width, "height": height,
                "tracking_failures": int(failures), "seconds": round(time.perf_counter() - started, 3),
                "processing_fps": round(len(poses) / elapsed, 2),
                "max_feature_points": 500, "adaptive_crop": adaptive,
                "mean_crop_zoom": round(float(np.mean(rendered_zooms)), 4),
                "max_crop_zoom": round(float(np.max(rendered_zooms)), 4),
                "max_crop_zoom_step": round(float(np.max(np.abs(np.diff(rendered_zooms)))), 6) if len(rendered_zooms) > 1 else 0.,
                "audio_preserved": False}
    finally:
        capture.release()
        for writer in writers:
            writer.release()
