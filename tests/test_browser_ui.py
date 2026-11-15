from pathlib import Path

import cv2
import numpy as np
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from video_stabilizer.web import inspect_video

APP = Path(__file__).resolve().parents[1] / "src" / "video_stabilizer" / "ui.py"


def clip(path, frames=12, fps=24):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 240))
    assert writer.isOpened()
    base = np.random.default_rng(42).integers(0, 256, (240, 320, 3), dtype=np.uint8)
    for i in range(frames):
        writer.write(cv2.warpAffine(base, np.float32([[1, 0, i % 2 * 4], [0, 1, 0]]), (320, 240)))
    writer.release()
    return path.read_bytes()


def test_upload_process_download_and_replace_input(tmp_path):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "SteadyFrame"
    assert any("Real handheld example" in caption.value for caption in app.caption)
    assert [tab.label for tab in app.tabs] == ["Real footage", "Synthetic benchmark"]
    assert any("97.30% measured jitter reduction" in caption.value for caption in app.caption)
    assert app.button[0].disabled
    data = clip(tmp_path / "source.mp4")
    app.file_uploader[0].set_value(("holiday.mp4", data, "video/mp4")).run()
    assert not app.button[0].disabled
    app.button[0].click().run()
    assert not app.exception
    assert app.success
    result = app.session_state["result"]
    assert result["report"]["frames"] == 12
    assert result["report"]["crop_zoom_limit"] == 1.25
    assert result["after"] and result["comparison"]
    assert len(app.get("download_button")) == 2
    encoded = tmp_path / "browser.mp4"
    encoded.write_bytes(result["after"])
    assert inspect_video(encoded)["frames"] == 12
    app.select_slider[0].set_value("Strong")
    app.button[0].click().run()
    assert app.success
    assert app.session_state["result"]["settings"][0] == "Strong"
    app.file_uploader[0].set_value(("different.mp4", clip(tmp_path / "other.mp4", frames=8), "video/mp4")).run()
    assert not app.success
    assert "result" not in app.session_state


def test_optional_comparison_and_audio_can_be_disabled(tmp_path):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.file_uploader[0].set_value(("source.mp4", clip(tmp_path / "source.mp4"), "video/mp4")).run()
    app.checkbox[0].uncheck()
    app.checkbox[1].uncheck()
    app.slider[1].set_value(1.15)
    app.button[0].click().run()
    assert not app.exception
    assert app.success
    assert app.session_state["result"]["comparison"] is None
    assert not app.session_state["result"]["report"]["audio_preserved"]
    assert app.session_state["result"]["report"]["crop_zoom_limit"] == 1.15
    assert len(app.get("download_button")) == 1


def test_invalid_video_displays_error_without_results():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.file_uploader[0].set_value(("broken.mp4", b"not a movie", "video/mp4")).run()
    app.button[0].click().run()
    assert not app.exception
    assert app.error
    assert "could not be read" in app.error[0].value
    assert "result" not in app.session_state


def test_browser_limits_reject_long_video(tmp_path):
    path = tmp_path / "long.mp4"
    clip(path, frames=16, fps=0.25)
    with pytest.raises(ValueError, match="60 seconds"):
        inspect_video(path)
