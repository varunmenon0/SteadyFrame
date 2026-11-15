"""Create labeled comparisons while retaining every source frame."""
import argparse
import math
from pathlib import Path
import subprocess
import tempfile

import cv2
import imageio_ffmpeg


def make_comparison(original, stabilized, video, preview, credit="", preview_seconds=8,
                    original_label="ORIGINAL / HANDHELD FOOTAGE", stabilized_label="STEADYFRAME / BALANCED",
                    playback_speed=1.):
    if not math.isfinite(playback_speed) or playback_speed <= 0:
        raise ValueError("Playback speed must be positive and finite")
    inputs = {Path(original).resolve(), Path(stabilized).resolve()}
    outputs = {Path(video).resolve(), Path(preview).resolve()}
    if inputs & outputs or len(outputs) != 2:
        raise ValueError("Comparison outputs must be distinct from each other and the input clips")
    first, second = cv2.VideoCapture(str(original)), cv2.VideoCapture(str(stabilized))
    writer = None
    try:
        fps = first.get(cv2.CAP_PROP_FPS)
        width, height = int(first.get(cv2.CAP_PROP_FRAME_WIDTH)), int(first.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if fps <= 0 or width < 4 or height < 4 or abs(fps - second.get(cv2.CAP_PROP_FPS)) > .01:
            raise ValueError("Readable clips with matching frame rates are required")
        Path(video).parent.mkdir(parents=True, exist_ok=True)
        Path(preview).parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="steadyframe-comparison-") as directory:
            labeled = Path(directory) / "labeled.mp4"
            text_scale = width / 1280
            header = round(72 * text_scale / 2) * 2
            playback_fps = fps * playback_speed
            writer = cv2.VideoWriter(str(labeled), cv2.VideoWriter_fourcc(*"mp4v"), playback_fps, (width * 2, height + header))
            if not writer.isOpened():
                raise ValueError("Cannot create comparison video")
            frames = 0
            while True:
                ok, a = first.read()
                other_ok, b = second.read()
                if ok != other_ok:
                    raise ValueError("Clips must have matching frame counts")
                if not ok:
                    break
                if a.shape != b.shape:
                    raise ValueError("Clips must have matching dimensions")
                canvas = cv2.copyMakeBorder(cv2.hconcat([a, b]), header, 0, 0, 0, cv2.BORDER_CONSTANT, value=(22, 22, 22))
                for x, label in [(round(20 * text_scale), original_label), (width + round(20 * text_scale), stabilized_label)]:
                    cv2.putText(canvas, label, (x, round(31 * text_scale)), cv2.FONT_HERSHEY_SIMPLEX, .85 * text_scale, (245, 245, 245), 2)
                if credit:
                    cv2.putText(canvas, credit, (round(20 * text_scale), round(58 * text_scale)), cv2.FONT_HERSHEY_SIMPLEX, .55 * text_scale, (200, 200, 200), 1)
                writer.write(canvas)
                frames += 1
            writer.release()
            if not frames:
                raise ValueError("No frames decoded")
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(labeled), "-vf", "scale=1920:-2",
                            "-c:v", "libx264", "-crf", "22", "-preset", "fast", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(video)], check=True)
            filters = "fps=10,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=48:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle"
            subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(video), "-t", str(preview_seconds),
                            "-filter_complex", filters, "-loop", "0", str(preview)], check=True)
            return {"frames": frames, "source_fps": fps, "fps": playback_fps,
                    "duration": frames / playback_fps, "playback_speed": playback_speed}
    finally:
        first.release()
        second.release()
        if writer is not None:
            writer.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("stabilized", type=Path)
    parser.add_argument("--video", type=Path, default=Path("docs/real-demo.mp4"))
    parser.add_argument("--preview", type=Path, default=Path("docs/real-demo.gif"))
    parser.add_argument("--credit", default="")
    parser.add_argument("--original-label", default="ORIGINAL / HANDHELD FOOTAGE")
    parser.add_argument("--stabilized-label", default="STEADYFRAME / BALANCED")
    parser.add_argument("--playback-speed", type=float, default=1., help="0.25 plays all source frames at four-times slow motion")
    args = parser.parse_args()
    print(make_comparison(args.original, args.stabilized, args.video, args.preview, args.credit,
                          original_label=args.original_label, stabilized_label=args.stabilized_label,
                          playback_speed=args.playback_speed))


if __name__ == "__main__":
    main()
