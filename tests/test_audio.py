import subprocess

import cv2
import imageio_ffmpeg
import numpy as np
import pytest

from video_stabilizer.audio import retain_audio
from video_stabilizer.core import stabilize


def decode_audio(path):
    return subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(path),
                           "-map", "0:a:0", "-f", "f32le", "-ac", "1", "-ar", "8000", "pipe:1"],
                          capture_output=True)


def test_export_retains_tone_trims_audio_and_supports_silent_option(tmp_path):
    source = tmp_path / "source with sound.mp4"
    output, comparison = tmp_path / "stabilized.mp4", tmp_path / "comparison.mp4"
    # Audio deliberately outlasts the 24 video frames to exercise trimming.
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                    "-c:v", "mpeg4", "-c:a", "aac", str(source)], check=True)
    report = stabilize(source, output, comparison=comparison)
    assert report["audio_preserved"]
    assert report["frames"] == 24
    for path, width in [(output, 320), (comparison, 640)]:
        audio = decode_audio(path)
        assert audio.returncode == 0, audio.stderr
        samples = np.frombuffer(audio.stdout, dtype=np.float32)
        assert 0.95 <= len(samples) / 8000 <= 1.1
        frequencies = np.fft.rfftfreq(len(samples), 1 / 8000)
        assert abs(frequencies[np.argmax(np.abs(np.fft.rfft(samples))) ] - 440) < 5
        capture = cv2.VideoCapture(str(path))
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 24
        assert capture.get(cv2.CAP_PROP_FPS) == 24
        assert capture.get(cv2.CAP_PROP_FRAME_WIDTH) == width
        capture.release()
    silent = tmp_path / "silent.mp4"
    assert not stabilize(source, silent, preserve_audio=False)["audio_preserved"]
    assert decode_audio(silent).returncode != 0


def test_mux_failure_retains_rendered_video_and_cleans_temporary_file(tmp_path, monkeypatch):
    output = tmp_path / "output.mp4"
    output.write_bytes(b"rendered-video")
    monkeypatch.setattr("video_stabilizer.audio.subprocess.run",
                        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", "encoder failed"))
    with pytest.raises(ValueError, match="video-only export retained"):
        retain_audio(tmp_path / "source.mp4", output, 1)
    assert output.read_bytes() == b"rendered-video"
    assert list(tmp_path.iterdir()) == [output]
