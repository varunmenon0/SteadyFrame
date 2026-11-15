import argparse
import json
from .core import stabilize


def main():
    parser = argparse.ArgumentParser(description="Stabilize camera shake and retain source audio.")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--radius", type=int, default=15, help="Smoothing radius in frames")
    parser.add_argument("--zoom", type=float, default=1.05, help="Minimum crop zoom, at least 1")
    parser.add_argument("--max-zoom", type=float, default=1.25, help="Maximum adaptive crop zoom; ease stabilization to preserve framing")
    parser.add_argument("--fixed-crop", action="store_true", help="Disable adaptive cropping and recentering")
    parser.add_argument("--comparison", help="Optional original/stabilized side-by-side video")
    parser.add_argument("--no-audio", action="store_true", help="Export silent video without audio muxing")
    args = parser.parse_args()
    try:
        report = stabilize(args.input, args.output, args.radius, args.zoom, args.comparison,
                           adaptive=not args.fixed_crop, preserve_audio=not args.no_audio, max_zoom=args.max_zoom)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
