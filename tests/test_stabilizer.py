import cv2
import numpy as np
import pytest
from video_stabilizer.core import adaptive_crop, estimate_motion, smooth_path, stabilize


@pytest.mark.parametrize("angle,tx,ty", [(0, 0, 0), (0, 40, -30), (15, -20, 10), (-25, 80, 20), (0, 500, -300)])
def test_adaptive_crop_has_no_exposed_border(angle, tx, ty):
    affine = cv2.getRotationMatrix2D((159.5, 119.5), angle, 1)
    affine[:, 2] += [tx, ty]
    correction = np.vstack([affine, [0, 0, 1]])
    transform, zoom = adaptive_crop(correction, 320, 240, minimum_zoom=1)
    image = np.full((240, 320), 255, dtype=np.uint8)
    result = cv2.warpAffine(image, transform[:2], (320, 240), borderMode=cv2.BORDER_CONSTANT)
    assert result.min() == 255
    assert zoom >= 1


def test_translation_and_textureless_fallback():
    image = np.random.default_rng(7).integers(0, 256, (240, 320), dtype=np.uint8)
    shifted = cv2.warpAffine(image, np.float32([[1, 0, 4], [0, 1, -3]]), (320, 240))
    motion, reliable = estimate_motion(image, shifted)
    assert reliable
    np.testing.assert_allclose(motion[:2, 2], [4, -3], atol=0.5)
    motion, reliable = estimate_motion(np.zeros_like(image), np.zeros_like(image))
    assert not reliable
    np.testing.assert_array_equal(motion, np.eye(3))


def test_smoothing_reduces_jitter():
    path = np.column_stack([np.tile([-5., 5.], 20), np.zeros((40, 2))])
    assert np.std(np.diff(smooth_path(path, 5)[:, 0])) < np.std(np.diff(path[:, 0])) / 3


def test_video_stabilization(tmp_path):
    source, output, comparison = [tmp_path / name for name in ("input.mp4", "output.mp4", "comparison.mp4")]
    rng = np.random.default_rng(42)
    base = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 30, (320, 240))
    assert writer.isOpened()
    for i in range(40):
        dx = 5 if i % 2 else -5
        writer.write(cv2.warpAffine(base, np.float32([[1, 0, dx], [0, 1, 0]]), (320, 240)))
    writer.release()
    report = stabilize(source, output, radius=5, zoom=1, comparison=comparison)
    assert report["frames"] == 40
    assert report["tracking_failures"] == 0
    def jitter(path, expected_width):
        capture = cv2.VideoCapture(str(path))
        frames = []
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            assert frame.shape == (240, expected_width, 3)
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        capture.release()
        assert len(frames) == 40
        return np.mean([np.linalg.norm(estimate_motion(a, b)[0][:2, 2]) for a, b in zip(frames, frames[1:])])
    assert jitter(output, 320) < jitter(source, 320) * 0.4
    jitter(comparison, 640)
    with pytest.raises(ValueError, match="different"):
        stabilize(source, source)
