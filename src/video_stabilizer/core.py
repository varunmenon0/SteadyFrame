"""Track features, smooth the camera path, and render corrected frames."""
from pathlib import Path
import time

import cv2
import numpy as np

from .audio import retain_audio


def is_scene_cut(previous, current):
    """Conservatively identify abrupt changes in luminance distribution.

    This heuristic can miss cuts between similarly lit scenes and can classify
    a strong exposure flash as a cut. It is not a semantic shot detector.
    """
    previous = cv2.resize(previous, (160, 90), interpolation=cv2.INTER_AREA)
    current = cv2.resize(current, (160, 90), interpolation=cv2.INTER_AREA)
    histograms = []
    for image in (previous, current):
        histogram = cv2.calcHist([image], [0], None, [32], [0, 256])
        histograms.append(cv2.normalize(histogram, None, norm_type=cv2.NORM_L1))
    distance = cv2.compareHist(*histograms, cv2.HISTCMP_BHATTACHARYYA)
    difference = float(np.mean(cv2.absdiff(previous, current)))
    return distance > 0.65 and difference > 35


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
    scale = np.hypot(affine[0, 0], affine[1, 0])
    if not np.isfinite(scale) or scale < 1e-6:
        return np.eye(3), False
    # Keep scale with translation: dropping scale alone turns a centered zoom
    # into a false camera pan because its translation still includes the zoom.
    return np.vstack([affine, [0, 0, 1]]), True


def smooth_path(path, radius):
    if radius < 0:
        raise ValueError("Smoothing radius must be nonnegative")
    if not radius:
        return path.copy()
    padded = np.pad(path, ((radius, radius), (0, 0)), mode="edge")
    kernel = np.ones(2 * radius + 1) / (2 * radius + 1)
    return np.column_stack([np.convolve(padded[:, i], kernel, mode="valid") for i in range(path.shape[1])])


def adaptive_crop(correction, width, height, minimum_zoom=1.05, crop_center=None):
    """Fit an output-aspect rectangle inside the transformed source footprint.

    Inverse-mapped corners must lie inside a one-pixel interpolation margin.
    Recenter by 10% of the transformed image center displacement, preserving
    most of the stabilization correction. This is geometric, not subject tracking.
    """
    center = np.array([(width - 1) / 2, (height - 1) / 2])
    half = center.copy()
    inverse = np.linalg.inv(correction)
    source_center = (correction @ np.r_[center, 1])[:2]
    if crop_center is None:
        crop_center = center + 0.1 * (source_center - center)
    crop_center = np.asarray(crop_center, dtype=float)

    def inside(candidate, scale):
        corners = candidate + np.array([[-1, -1], [-1, 1], [1, -1], [1, 1]]) * half * scale
        mapped = np.column_stack([corners, np.ones(4)]) @ inverse.T
        return bool(((mapped[:, :2] >= 1) & (mapped[:, :2] <= [width - 2, height - 2])).all())

    # Extreme displacements may put the nominal crop center outside the image.
    if not inside(crop_center, 0):
        crop_center = source_center
    motion_scale = np.hypot(correction[0, 0], correction[1, 0])
    low, high = 0., motion_scale / minimum_zoom
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
    return crop @ correction, scale * motion_scale


def blend_correction(correction, amount, width, height):
    """Blend a similarity correction toward identity around the frame center."""
    center = np.array([(width - 1) / 2, (height - 1) / 2])
    displacement = (correction @ np.r_[center, 1])[:2] - center
    angle = amount * np.arctan2(correction[1, 0], correction[0, 0])
    scale = np.hypot(correction[0, 0], correction[1, 0]) ** amount
    linear = scale * np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    result = np.eye(3)
    result[:2, :2] = linear
    result[:2, 2] = center + amount * displacement - linear @ center
    return result


def crop_at_strength(correction, crop_center, amount, width, height, minimum_zoom):
    center = np.array([(width - 1) / 2, (height - 1) / 2])
    candidate = blend_correction(correction, amount, width, height)
    return adaptive_crop(candidate, width, height, minimum_zoom,
                         crop_center=center + amount * (crop_center - center))


def plan_bounded_crops(corrections, centers, width, height, minimum_zoom, maximum_zoom, fps, scenes):
    """Find border-safe corrections within the zoom budget, then ease strength.

    Less stabilization is applied where a full correction would crop too much.
    Strength envelopes anticipate those frames instead of changing abruptly.
    """
    strengths = np.ones(len(corrections))
    _, neutral_zoom = adaptive_crop(np.eye(3), width, height, minimum_zoom)
    if neutral_zoom > maximum_zoom + 1e-7:
        raise ValueError("Maximum crop zoom is too small for this video's dimensions")
    for i, (correction, center) in enumerate(zip(corrections, centers)):
        _, required = crop_at_strength(correction, center, 1., width, height, minimum_zoom)
        if required <= maximum_zoom:
            continue
        low, high = 0., 1.
        for _ in range(24):
            mid = (low + high) / 2
            _, required = crop_at_strength(correction, center, mid, width, height, minimum_zoom)
            if required <= maximum_zoom:
                low = mid
            else:
                high = mid
        strengths[i] = low
    for start, end in scenes:
        step = 0.5 / fps
        for i in range(start + 1, end):
            strengths[i] = min(strengths[i], strengths[i - 1] + step)
        for i in range(end - 2, start - 1, -1):
            strengths[i] = min(strengths[i], strengths[i + 1] + step)
    transforms, zooms = [], []
    for i, (correction, center, amount) in enumerate(zip(corrections, centers, strengths)):
        transform, required = crop_at_strength(correction, center, amount, width, height, minimum_zoom)
        # Geometric feasibility need not be globally monotone for extreme
        # rotations. Recheck after easing instead of assuming the search held.
        while required > maximum_zoom + 1e-7 and amount > 1e-7:
            amount *= .9
            transform, required = crop_at_strength(correction, center, amount, width, height, minimum_zoom)
        if required > maximum_zoom + 1e-7:
            amount = 0.
            transform, required = crop_at_strength(correction, center, 0., width, height, minimum_zoom)
        strengths[i] = amount
        transforms.append(transform)
        zooms.append(required)
    return transforms, zooms, strengths


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


def plan_crop_centers(corrections, width, height, fps, scenes):
    """Smooth geometric recentering over a quarter-second radius per shot."""
    center = np.array([(width - 1) / 2, (height - 1) / 2])
    centers = np.array([center + 0.1 * ((matrix @ np.r_[center, 1])[:2] - center)
                        for matrix in corrections])
    for start, end in scenes:
        centers[start:end] = smooth_path(centers[start:end], max(1, round(fps * 0.25)))
    return centers


def stabilize(source, destination, radius=15, zoom=1.05, comparison=None, adaptive=True, preserve_audio=True, progress=None, max_zoom=1.25):
    source, destination = Path(source), Path(destination)
    paths = [source.resolve(), destination.resolve()]
    if comparison:
        paths.append(Path(comparison).resolve())
    if len(set(paths)) != len(paths):
        raise ValueError("Input, output, and comparison paths must be different")
    if radius < 0 or not np.isfinite(zoom) or zoom < 1:
        raise ValueError("Radius must be nonnegative and zoom must be finite and at least 1")
    if not np.isfinite(max_zoom) or max_zoom < zoom:
        raise ValueError("Maximum zoom must be finite and at least the minimum crop zoom")
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
        estimated_frames = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        if progress:
            progress("tracking", 0, estimated_frames)
        poses = [np.eye(3)]
        scene_starts = [0]
        failures = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            current = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if is_scene_cut(previous, current):
                scene_starts.append(len(poses))
                poses.append(np.eye(3))
            else:
                motion, reliable = estimate_motion(previous, current)
                poses.append(motion @ poses[-1])
                failures += not reliable
            previous = current
            if progress and len(poses) % 10 == 0:
                progress("tracking", len(poses), estimated_frames)
        if progress:
            progress("planning", 0, len(poses))
        path = np.array([[p[0, 2], p[1, 2], np.arctan2(p[1, 0], p[0, 0]),
                          np.log(np.hypot(p[0, 0], p[1, 0]))] for p in poses])
        scenes = list(zip(scene_starts, scene_starts[1:] + [len(poses)]))
        smoothed = np.empty_like(path)
        for start, end in scenes:
            path[start:end, 2] = np.unwrap(path[start:end, 2])
            smoothed[start:end] = smooth_path(path[start:end], radius)
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
        for i, pose in enumerate(poses):
            x, y, angle, log_scale = smoothed[i]
            c, s = np.exp(log_scale) * np.array([np.cos(angle), np.sin(angle)])
            target = np.array([[c, -s, x], [s, c, y], [0, 0, 1]])
            correction = target @ np.linalg.inv(pose)
            corrections.append(correction)
        centers = plan_crop_centers(corrections, width, height, fps, scenes) if adaptive else [None] * len(poses)
        if adaptive:
            corrections, crop_zooms, strengths = plan_bounded_crops(
                corrections, centers, width, height, zoom, max_zoom, fps, scenes)
        else:
            corrections = [zoom_matrix @ correction for correction in corrections]
            crop_zooms = [np.hypot(correction[0, 0], correction[1, 0]) for correction in corrections]
            strengths = np.ones(len(corrections))
        # Express the limit per second so 30 and 120 FPS clips behave alike.
        rendered_zooms = np.array(crop_zooms)
        if adaptive:
            for start, end in scenes:
                rendered_zooms[start:end] = smooth_crop_zooms(crop_zooms[start:end], max_step=0.15 / fps)
        center = np.array([(width - 1) / 2, (height - 1) / 2])
        if progress:
            progress("rendering", 0, len(poses))
        for index, (correction, required, applied) in enumerate(zip(corrections, crop_zooms, rendered_zooms)):
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
            if progress and ((index + 1) % 10 == 0 or index == len(poses) - 1):
                progress("rendering", index + 1, len(poses))
        # Finalize containers before FFmpeg reads them (particularly important
        # for MP4, whose index is written when the OpenCV writer closes).
        for writer in writers:
            writer.release()
        capture.release()
        audio_preserved = False
        if preserve_audio:
            if progress:
                progress("audio", 0, 1)
            audio_preserved = retain_audio(source, destination, len(poses) / fps)
            if comparison:
                retain_audio(source, comparison, len(poses) / fps)
        if progress:
            progress("complete", 1, 1)
        elapsed = time.perf_counter() - started
        return {"frames": len(poses), "fps": fps, "width": width, "height": height,
                "tracking_failures": int(failures), "seconds": round(time.perf_counter() - started, 3),
                "processing_fps": round(len(poses) / elapsed, 2),
                "max_feature_points": 500, "adaptive_crop": adaptive,
                "scene_cuts": len(scene_starts) - 1,
                "scene_cut_frames": scene_starts[1:],
                "mean_crop_zoom": round(float(np.mean(rendered_zooms)), 4),
                "max_crop_zoom": round(float(np.max(rendered_zooms)), 4),
                "crop_zoom_limit": max_zoom if adaptive else None,
                "crop_limited_frames": int(np.sum(strengths < 1 - 1e-6)),
                "minimum_correction_strength": round(float(np.min(strengths)), 4),
                "max_crop_zoom_step": round(float(np.max(np.abs(np.diff(rendered_zooms)))), 6) if len(rendered_zooms) > 1 else 0.,
                "audio_preserved": audio_preserved}
    finally:
        capture.release()
        for writer in writers:
            writer.release()
