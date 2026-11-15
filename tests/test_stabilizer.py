import cv2
import numpy as np
import pytest
from video_stabilizer.core import adaptive_crop, estimate_motion, plan_bounded_crops, plan_crop_centers, smooth_crop_zooms, smooth_path, stabilize


def test_crop_limit_preserves_pixels_and_eases_strong_corrections():
    corrections = []
    for angle, tx in [(0, 0), (15, 50), (-12, -60), (0, 0)]:
        affine = cv2.getRotationMatrix2D((159.5, 119.5), angle, 1.04)
        affine[:, 2] += [tx, 0]
        corrections.append(np.vstack([affine, [0, 0, 1]]))
    scenes = [(0, len(corrections))]
    centers = plan_crop_centers(corrections, 320, 240, 30, scenes)
    transforms, zooms, strengths = plan_bounded_crops(corrections, centers, 320, 240, 1.05, 1.25, 30, scenes)
    assert np.min(strengths) < 0.9
    assert max(zooms) <= 1.25 + 1e-7
    assert np.max(np.abs(np.diff(strengths))) <= .5 / 30 + 1e-6
    for transform, required, applied in zip(transforms, zooms, smooth_crop_zooms(zooms)):
        extra = applied / required
        envelope = np.array([[extra, 0, 159.5 * (1-extra)], [0, extra, 119.5 * (1-extra)], [0, 0, 1]])
        final = envelope @ transform
        assert np.hypot(final[0, 0], final[1, 0]) <= 1.25 + 1e-7
        result = cv2.warpAffine(np.full((240, 320), 255, np.uint8), final[:2], (320, 240), borderMode=cv2.BORDER_CONSTANT)
        assert result.min() == 255


def test_total_crop_zoom_includes_motion_scale():
    correction = np.vstack([cv2.getRotationMatrix2D((159.5, 119.5), 0, 1.3), [0, 0, 1]])
    transform, zoom = adaptive_crop(correction, 320, 240, minimum_zoom=1.05)
    assert zoom == pytest.approx(1.05, abs=1e-6)
    assert np.hypot(transform[0, 0], transform[1, 0]) == pytest.approx(zoom)


def test_recenter_smoothing_reduces_jitter_and_resets_at_cuts():
    corrections = []
    for i in range(30):
        matrix = np.eye(3)
        matrix[0, 2] = (-20 if i % 2 else 20) if i < 20 else 80
        corrections.append(matrix)
    centers = plan_crop_centers(corrections, 320, 240, 30, [(0, 20), (20, 30)])
    assert np.max(np.abs(np.diff(centers[:20, 0]))) < 1
    # The new shot's center must not be pulled toward the preceding shot.
    np.testing.assert_allclose(centers[20:, 0], 167.5)
    for correction, center in zip(corrections, centers):
        transform, _ = adaptive_crop(correction, 320, 240, crop_center=center)
        result = cv2.warpAffine(np.full((240, 320), 255, np.uint8), transform[:2], (320, 240), borderMode=cv2.BORDER_CONSTANT)
        assert result.min() == 255


def test_zoom_envelope_anticipates_peaks_and_preserves_coverage():
    required = np.array([1.05, 1.05, 1.4, 1.05, 1.05, 1.2, 1.05])
    smoothed = smooth_crop_zooms(required, max_step=0.02)
    assert (smoothed >= required).all()
    assert np.max(np.abs(np.diff(smoothed))) <= 0.02 + 1e-12
    assert smoothed[0] > required[0]
    assert smoothed[-1] > required[-1]
    np.testing.assert_allclose(smooth_crop_zooms([1.05] * 10), 1.05)


def test_zoom_envelope_rejects_invalid_values():
    for values in ([np.nan], [0.9], [[1.1]]):
        with pytest.raises(ValueError):
            smooth_crop_zooms(values)
    with pytest.raises(ValueError):
        smooth_crop_zooms([1.1], max_step=0)


def test_temporal_crop_keeps_rotated_frames_border_free():
    corrections, required = [], []
    for angle in [0, 2, 15, -5, 0]:
        affine = cv2.getRotationMatrix2D((159.5, 119.5), angle, 1)
        transform, zoom = adaptive_crop(np.vstack([affine, [0, 0, 1]]), 320, 240)
        corrections.append(transform)
        required.append(zoom)
    for transform, raw, applied in zip(corrections, required, smooth_crop_zooms(required)):
        extra = applied / raw
        envelope = np.array([[extra, 0, 159.5 * (1 - extra)], [0, extra, 119.5 * (1 - extra)], [0, 0, 1]])
        image = np.full((240, 320), 255, dtype=np.uint8)
        result = cv2.warpAffine(image, (envelope @ transform)[:2], (320, 240), borderMode=cv2.BORDER_CONSTANT)
        assert result.min() == 255


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


def test_centered_zoom_does_not_turn_into_a_false_pan():
    image = np.random.default_rng(9).integers(0, 256, (480, 640), dtype=np.uint8)
    image = cv2.GaussianBlur(image, (3, 3), 0)
    expected = cv2.getRotationMatrix2D((319.5, 239.5), 0, 1.025)
    zoomed = cv2.warpAffine(image, expected, (640, 480))
    motion, reliable = estimate_motion(image, zoomed)
    assert reliable
    np.testing.assert_allclose(motion[:2], expected, atol=0.4)
    center = np.array([319.5, 239.5, 1])
    np.testing.assert_allclose((motion @ center)[:2], center[:2], atol=0.4)


def test_degenerate_zoom_fit_falls_back_to_identity(monkeypatch):
    image = np.random.default_rng(10).integers(0, 256, (240, 320), dtype=np.uint8)
    monkeypatch.setattr(cv2, "estimateAffinePartial2D", lambda *a, **kw: (np.zeros((2, 3)), np.ones((10, 1), np.uint8)))
    motion, reliable = estimate_motion(image, image)
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
    events = []
    report = stabilize(source, output, radius=5, zoom=1, comparison=comparison,
                       progress=lambda stage, done, total: events.append((stage, done, total)))
    assert report["frames"] == 40
    assert report["tracking_failures"] == 0
    assert report["max_crop_zoom"] <= 1.25
    assert not report["audio_preserved"]
    assert events[0][0] == "tracking"
    assert ("rendering", 40, 40) in events
    assert events[-1] == ("complete", 1, 1)
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
