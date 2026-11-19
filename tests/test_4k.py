import cv2
import numpy as np
import pytest

from video_stabilizer.core import estimate_motion, stabilize
from video_stabilizer.web import encode_for_browser, inspect_video


@pytest.mark.parametrize("width,height", [(3840,2160),(4096,2160),(2160,3840),(2160,4096)])
def test_accepts_uhd_and_dci_in_both_orientations(tmp_path, width, height):
    path = tmp_path / "4k.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 24, (width,height))
    assert writer.isOpened()
    writer.write(np.full((height,width,3),128,np.uint8))
    writer.release()
    info = inspect_video(path)
    assert (info["width"],info["height"]) == (width,height)


@pytest.mark.parametrize("width,height", [(4098,2160),(3840,2162)])
def test_rejects_dimensions_beyond_4k(tmp_path, width, height):
    path = tmp_path / "too-large.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),24,(width,height))
    assert writer.isOpened()
    writer.write(np.full((height,width,3),128,np.uint8))
    writer.release()
    with pytest.raises(ValueError,match="up to 4K"):
        inspect_video(path)


@pytest.mark.parametrize("width,height", [(3840,2160),(4096,2160),(2160,4096)])
def test_tracking_returns_native_pixel_motion_for_4k(width, height):
    base = np.random.default_rng(71).integers(0,256,(540,960),dtype=np.uint8)
    image = cv2.resize(base,(width,height))
    shifted = cv2.warpAffine(image,np.float32([[1,0,12],[0,1,-8]]),(width,height))
    transform,reliable = estimate_motion(image,shifted)
    assert reliable
    np.testing.assert_allclose(transform[:2,2],[12,-8],atol=.6)


def test_4k_render_and_browser_export_keep_resolution(tmp_path):
    source,output,comparison = [tmp_path/name for name in ("input.mp4","output.mp4","comparison.mp4")]
    base = np.random.default_rng(72).integers(0,256,(540,960,3),dtype=np.uint8)
    frame = cv2.resize(base,(3840,2160))
    writer = cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*"mp4v"),24,(3840,2160))
    assert writer.isOpened()
    for shift in [0,12,-12,0]:
        writer.write(cv2.warpAffine(frame,np.float32([[1,0,shift],[0,1,0]]),(3840,2160)))
    writer.release()
    report = stabilize(source,output,radius=2,comparison=comparison,preserve_audio=False)
    assert report["frames"] == 4
    assert report["tracking_failures"] == 0
    for raw,width in [(output,3840),(comparison,7680)]:
        browser = tmp_path/("browser-"+raw.name)
        encode_for_browser(raw,browser,preserve_audio=False)
        capture = cv2.VideoCapture(str(browser))
        decoded = 0
        while True:
            ok,result = capture.read()
            if not ok: break
            assert result.shape == (2160,width,3)
            decoded += 1
        assert capture.get(cv2.CAP_PROP_FPS) == 24
        capture.release()
        assert decoded == 4
