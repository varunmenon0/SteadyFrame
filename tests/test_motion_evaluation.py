import cv2
import numpy as np
import pytest

from tools.evaluate_motion import compare_motion


def write_fixture(path, offsets, blank=False):
    base = np.random.default_rng(5).integers(0, 256, (240, 320, 3), dtype=np.uint8)
    if blank:
        base[:] = 128
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 24, (320, 240))
    assert writer.isOpened()
    for offset in offsets:
        writer.write(cv2.warpAffine(base, np.float32([[1, 0, offset], [0, 1, 0]]), (320, 240)))
    writer.release()


def test_motion_evaluation_detects_known_shake_reduction(tmp_path):
    original, stabilized = tmp_path / "shaky.mp4", tmp_path / "stable.mp4"
    write_fixture(original, [-4, 4] * 8)
    write_fixture(stabilized, [0] * 16)
    report = compare_motion([original, stabilized])
    assert report["shared_triplet_coverage"] >= .8
    assert report["clips"]["stable.mp4"]["estimated_jitter_reduction_percent"] > 90


def test_motion_evaluation_refuses_untrackable_footage(tmp_path):
    first, second = tmp_path / "first.mp4", tmp_path / "second.mp4"
    write_fixture(first, [0] * 8, blank=True)
    write_fixture(second, [0] * 8, blank=True)
    with pytest.raises(ValueError, match="no score reported"):
        compare_motion([first, second])


def test_motion_evaluation_requires_matching_frame_counts(tmp_path):
    first, second = tmp_path / "first.mp4", tmp_path / "second.mp4"
    write_fixture(first, [0] * 8)
    write_fixture(second, [0] * 12)
    with pytest.raises(ValueError, match="matching frame counts"):
        compare_motion([first, second])
