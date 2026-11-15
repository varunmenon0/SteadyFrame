"""Compare global motion estimates on the same reliable frame triplets."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def clip_motion(path):
    capture = cv2.VideoCapture(str(path))
    detector = cv2.ORB_create(nfeatures=1800)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    previous = None
    vectors, counts = [], []
    fps = capture.get(cv2.CAP_PROP_FPS)
    size = None
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            height, width = frame.shape[:2]
            size = (width, height)
            points, descriptors = detector.detectAndCompute(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), None)
            if previous is not None:
                old_points, old_descriptors = previous
                vector, count = np.full(4, np.nan), 0
                if old_descriptors is not None and descriptors is not None and len(descriptors) >= 2:
                    pairs = matcher.knnMatch(old_descriptors, descriptors, k=2)
                    matches = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < .7 * pair[1].distance]
                    if len(matches) >= 12:
                        source = np.float32([old_points[match.queryIdx].pt for match in matches])
                        target = np.float32([points[match.trainIdx].pt for match in matches])
                        affine, inliers = cv2.estimateAffinePartial2D(source, target, method=cv2.RANSAC, ransacReprojThreshold=2.5)
                        if affine is not None and inliers is not None:
                            count = int(inliers.sum())
                            scale = np.hypot(affine[0, 0], affine[1, 0])
                            if count >= 12 and count / len(matches) >= .5 and np.isfinite(affine).all() and scale > 0:
                                center = np.array([width / 2, height / 2, 1])
                                displacement = affine @ center - center[:2]
                                angle = np.arctan2(affine[1, 0], affine[0, 0])
                                vector = np.r_[displacement, angle * np.hypot(width, height) / 2, np.log(scale)]
                vectors.append(vector)
                counts.append(count)
            previous = points, descriptors
    finally:
        capture.release()
    if len(vectors) < 2 or not np.isfinite(fps) or fps <= 0:
        raise ValueError(f"Cannot evaluate {Path(path).name}: at least three readable frames and a valid frame rate are required")
    return np.asarray(vectors), np.asarray(counts), fps, size


def compare_motion(paths, minimum_coverage=.8):
    if len(paths) < 2:
        raise ValueError("Provide an original clip and at least one output")
    if not 0 < minimum_coverage <= 1:
        raise ValueError("Minimum coverage must be between 0 and 1")
    names = [Path(path).name for path in paths]
    if len(set(names)) != len(names):
        raise ValueError("Use distinct filenames for the original and each output")
    clips = [clip_motion(path) for path in paths]
    reference = clips[0]
    if any(len(clip[0]) != len(reference[0]) or clip[3] != reference[3] or not np.isclose(clip[2], reference[2]) for clip in clips[1:]):
        raise ValueError("Clips must have matching frame counts, dimensions, and frame rates")
    valid = np.logical_and.reduce([np.isfinite(clip[0]).all(axis=1) for clip in clips])
    triplets = valid[1:] & valid[:-1]
    if not triplets.any() or triplets.mean() < minimum_coverage:
        raise ValueError(f"Reliable shared triplets cover {triplets.mean():.1%}; no score reported")
    report = {
        "method": "ORB descriptor matches and RANSAC similarity transforms; RMS change in frame-center displacement and rotation (pixel-equivalent).",
        "evaluated_triplets": int(triplets.sum()), "total_triplets": len(triplets),
        "shared_triplet_coverage": float(triplets.mean()),
        "note": "Same reliable frame triplets for all clips. Estimated global image motion, not ground truth or a perceptual quality score.",
        "clips": {},
    }
    for name, (vectors, inliers, _, _) in zip(names, clips):
        changes = np.diff(vectors, axis=0)[triplets]
        report["clips"][name] = {
            "motion_jitter_rms": float(np.sqrt(np.mean(np.sum(changes[:, :3] ** 2, axis=1)))),
            "zoom_acceleration_rms": float(np.sqrt(np.mean(changes[:, 3] ** 2))),
            "median_inliers": float(np.median(inliers[valid])),
        }
    baseline = report["clips"][names[0]]["motion_jitter_rms"]
    for name in names[1:]:
        report["clips"][name]["estimated_jitter_reduction_percent"] = (
            100 * (1 - report["clips"][name]["motion_jitter_rms"] / baseline) if baseline > 1e-8 else None)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("videos", nargs="+", type=Path, help="Original first, followed by stabilized versions")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = compare_motion(args.videos)
    except ValueError as error:
        parser.error(str(error))
    output = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output)
    print(output)


if __name__ == "__main__":
    main()
