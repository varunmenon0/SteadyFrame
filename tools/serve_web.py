"""Preview the static browser app with the same headers used on Vercel."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEADERS = json.loads((ROOT / "vercel.json").read_text())["headers"][0]["headers"]


class PreviewHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        for header in HEADERS:
            self.send_header(header["key"], header["value"])
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    handler = partial(PreviewHandler, directory=str(ROOT / "web"))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"SteadyFrame: http://127.0.0.1:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
