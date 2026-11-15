"""Validation and browser-compatible exports for the local interface."""
from pathlib import Path
import subprocess

import cv2
import imageio_ffmpeg
import numpy as np


def inspect_video(path):
    capture = cv2.VideoCapture(str(path))
    try:
        ok, frame = capture.read()
        if not ok:
            raise ValueError("This file could not be read as a video. Try an MP4 or MOV file.")
        height, width = frame.shape[:2]
        fps = capture.get(cv2.CAP_PROP_FPS)
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if not np.isfinite([fps, frames]).all() or fps <= 0 or frames < 1:
            raise ValueError("This video has invalid timing information.")
        if min(width, height) < 4 or max(width, height) > 1920 or width * height > 1920 * 1080:
            raise ValueError("Please use a video up to 1080p (landscape or portrait).")
        if fps > 120.1 or frames / fps > 60.1:
            raise ValueError("Please use a clip up to 60 seconds and 120 FPS.")
        return {"width": width, "height": height, "fps": fps, "frames": int(frames), "duration": frames / fps}
    finally:
        capture.release()


def encode_for_browser(source, destination, preserve_audio=True):
    """Use H.264/AAC for playback across mainstream browsers."""
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-nostdin", "-y",
               "-i", str(Path(source).resolve()), "-map", "0:v:0"]
    if preserve_audio:
        command += ["-map", "0:a:0?"]
    command += ["-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-movflags", "+faststart", str(Path(destination).resolve())]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise ValueError("Could not prepare browser playback. Try a different source clip.")
