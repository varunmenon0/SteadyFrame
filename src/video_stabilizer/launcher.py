"""Launch the browser interface on this computer only."""
from pathlib import Path
import subprocess
import sys


def main():
    try:
        import streamlit  # noqa: F401
    except ImportError:
        raise SystemExit("Install the browser interface with: pip install 'video-stabilizer[ui]'")
    app = Path(__file__).with_name("ui.py")
    try:
        subprocess.run([sys.executable, "-m", "streamlit", "run", str(app),
                        "--server.address=127.0.0.1", "--server.maxUploadSize=100",
                        "--browser.gatherUsageStats=false", "--server.headless=false"], check=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
