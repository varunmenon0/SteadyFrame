import cv2
import numpy as np

from video_stabilizer.core import is_scene_cut, stabilize


def test_camera_pan_and_small_exposure_change_are_not_cuts():
    image = np.random.default_rng(8).integers(20, 180, (240, 320), dtype=np.uint8)
    shifted = cv2.warpAffine(image, np.float32([[1, 0, 8], [0, 1, -5]]), (320, 240), borderMode=cv2.BORDER_REFLECT)
    assert not is_scene_cut(image, shifted)
    assert not is_scene_cut(image, image + 10)


def write_video(path, frames):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (320, 240))
    assert writer.isOpened()
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()


def read_video(path):
    capture = cv2.VideoCapture(str(path))
    frames = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                return frames
            frames.append(frame)
    finally:
        capture.release()


def test_cut_resets_motion_and_does_not_shift_the_new_scene(tmp_path):
    rng = np.random.default_rng(19)
    dark = rng.integers(10, 90, (240, 320, 3), dtype=np.uint8)
    bright = rng.integers(170, 250, (240, 320, 3), dtype=np.uint8)
    first_scene = [cv2.warpAffine(dark, np.float32([[1, 0, i * 2], [0, 1, 0]]), (320, 240), borderMode=cv2.BORDER_REFLECT) for i in range(16)]
    second_scene = [bright] * 16
    source, output = tmp_path / "cuts.mp4", tmp_path / "stabilized.mp4"
    write_video(source, first_scene + second_scene)
    report = stabilize(source, output, radius=10, zoom=1, adaptive=False)
    assert report["scene_cuts"] == 1
    assert report["scene_cut_frames"] == [16]
    assert report["tracking_failures"] == 0
    original, stabilized = read_video(source), read_video(output)
    assert len(stabilized) == 32
    # A stationary second scene should remain aligned, including its first frame.
    for before, after in zip(original[16:], stabilized[16:]):
        shift, response = cv2.phaseCorrelate(np.float32(cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)), np.float32(cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)))
        assert response > 0.5
        assert np.linalg.norm(shift) < 0.3


def test_single_frame_video_is_supported(tmp_path):
    source, output = tmp_path / "single.mp4", tmp_path / "out.mp4"
    write_video(source, [np.full((240, 320, 3), 128, dtype=np.uint8)])
    report = stabilize(source, output)
    assert report["frames"] == 1
    assert report["scene_cuts"] == 0
    assert len(read_video(output)) == 1
