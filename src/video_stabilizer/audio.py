"""Retain source audio without re-encoding the stabilized video stream."""
from pathlib import Path
import re
import subprocess
import tempfile

import imageio_ffmpeg


def retain_audio(source, destination, duration):
    """Mux the first source audio track as AAC, trimmed to the video duration.

    A source without audio remains silent. Replace the rendered file only after
    FFmpeg succeeds so a muxing error does not destroy the video-only export.
    """
    destination = Path(destination)
    with tempfile.NamedTemporaryFile(prefix=".stabilizer-audio-", suffix=destination.suffix,
                                     dir=destination.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-nostdin", "-y",
                   "-i", str(destination.resolve()), "-i", str(Path(source).resolve()),
                   "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac",
                   "-t", str(duration), str(temporary_path.resolve())]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise ValueError(f"Audio muxing failed; video-only export retained: {result.stderr[-2000:]}")
        # The rendered input has no audio, so stream #0 Audio entries describe
        # the output. FFmpeg's optional map also succeeds for silent inputs.
        has_audio = bool(re.search(r"Stream #0:\d+[^\n]*Audio:", result.stderr))
        temporary_path.replace(destination)
        return has_audio
    finally:
        temporary_path.unlink(missing_ok=True)
