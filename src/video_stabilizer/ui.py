"""SteadyFrame local browser interface. Run with steadyframe-ui."""
import hashlib
import json
import logging
from pathlib import Path
import tempfile

import streamlit as st

from video_stabilizer.core import stabilize
from video_stabilizer.web import encode_for_browser, inspect_video

st.set_page_config(page_title="SteadyFrame", page_icon=":material/movie:", layout="wide")
st.markdown("""
<style>
.block-container {max-width: 1320px; padding: 1.4rem 2.5rem 1.5rem;}
h1, h2, h3, p, label, button, input {
    font-family: "Avenir Next", Avenir, "Segoe UI", sans-serif;
}
h1, h2, h3 {font-family: "Avenir Next", Avenir, "Segoe UI", sans-serif !important;}
h1 {font-size: 2rem !important; letter-spacing: -.035em; font-weight: 600 !important; padding-bottom: .35rem;}
h3 {font-size: 1.05rem !important; letter-spacing: -.01em; font-weight: 600 !important;}
[data-testid="stMarkdownContainer"] p {line-height: 1.55;}
[data-testid="stCaptionContainer"] p {font-size: .875rem; line-height: 1.5; color: #5c666c;}
[data-testid="stCaptionContainer"] {opacity: 1;}
[data-testid="stToolbar"] {visibility: hidden;}
[data-testid="stForm"] {padding: 0; border: 0;}
[data-testid="stFileUploader"] {background: #fff; border: 1px solid #ccd2d2; border-radius: 4px; padding: .25rem;}
button[kind="primary"], button[kind="secondary"] {border-radius: 4px; box-shadow: none; font-weight: 500;}
button[kind="primary"] {background: #2855ad; border-color: #2855ad; color: #fff;}
button[kind="primary"]:hover {background: #20468f; border-color: #20468f; color: #fff;}
button[kind="primary"]:disabled {background: #e2e5e5; border-color: #d6dcdc; color: #687278;}
video {border-radius: 2px !important; background: #16191b;}
hr {border-color: #d5dad9; margin: .4rem 0 1rem !important;}
.app-intro {font-size: .95rem; color: #515b60; margin-bottom: .35rem;}
.clip-details {font-size: .875rem; color: #515b60; border-top: 1px solid #d5dad9; padding-top: .75rem;}
@media (min-width: 761px) {
  [data-testid="stHorizontalBlock"]:has([data-testid="stFileUploader"]) > [data-testid="stColumn"]:first-child {
      padding-right: 1.5rem; border-right: 1px solid #d5dad9;
  }
}
@media (max-width: 760px) {
  .block-container {padding: 1.3rem 1.2rem;}
  h1 {font-size: 1.65rem !important;}
  [data-testid="stHorizontalBlock"]:has([data-testid="stFileUploader"]) {flex-direction: column;}
  [data-testid="stHorizontalBlock"]:has([data-testid="stFileUploader"]) > [data-testid="stColumn"] {
      width: 100% !important; flex: 1 1 100% !important;
  }
}
</style>
""", unsafe_allow_html=True)
st.title("SteadyFrame")
st.markdown('<p class="app-intro">Smooth a clip, compare the result, and save a copy.</p>', unsafe_allow_html=True)
st.caption("Local processing. Your video stays on this computer.")
st.divider()

controls, workspace = st.columns([1, 2.6], gap="large")
with controls:
    st.subheader("Source")
    uploaded = st.file_uploader("Choose a video", type=["mp4", "mov", "m4v", "avi", "mkv"],
                                help="Drop a video here or browse your files.")
    st.caption("Up to 100 MB · 60 seconds · 1080p · 120 FPS input")
    identity = hashlib.sha256(uploaded.getbuffer()).hexdigest() if uploaded else None
    if st.session_state.get("input_identity") != identity:
        st.session_state.pop("result", None)
        st.session_state["input_identity"] = identity
    with st.form("settings", border=False):
        st.subheader("Adjustments")
        strength = st.select_slider("Stabilization strength", ["Gentle", "Balanced", "Strong"], value="Balanced")
        st.caption("Start with Balanced. Strong also softens deliberate camera movement.")
        crop = st.slider("Minimum crop", 0, 15, 5, format="%d%%",
                         help="A small crop hides moving borders. Extra cropping is added automatically when needed.")
        maximum_zoom = st.slider("Maximum zoom", 1.15, 1.60, 1.25, step=0.05, format="%.2f×",
                                 help="Limits crop magnification. Stabilization is eased during large movements to preserve framing.")
        sound = st.checkbox("Keep audio", value=True)
        comparison = st.checkbox("Include side-by-side download", value=True)
        submitted = st.form_submit_button("Stabilize video", type="primary", disabled=uploaded is None,
                                          use_container_width=True)
    st.caption("Borders are cropped automatically. The original file is kept.")

with workspace:
    st.subheader("Preview")
    if submitted:
        st.session_state.pop("result", None)
        bar = st.progress(0, text="Checking your clip…")

        def update(stage, completed, total):
            ranges = {"tracking": (0.02, 0.40, "Tracking camera movement"),
                      "planning": (0.42, 0.42, "Planning a smoother camera path"),
                      "rendering": (0.45, 0.80, "Rendering stabilized frames"),
                      "audio": (0.82, 0.82, "Restoring audio"),
                      "complete": (0.85, 0.85, "Preparing browser playback")}
            low, high, label = ranges[stage]
            fraction = min(1., completed / max(1, total))
            bar.progress(low + (high - low) * fraction, text=label + "…")

        try:
            if uploaded.size > 100 * 1024 * 1024:
                raise ValueError("Please choose a video smaller than 100 MB.")
            with tempfile.TemporaryDirectory(prefix="steadyframe-") as directory:
                work = Path(directory)
                source = work / ("input" + Path(uploaded.name).suffix.lower())
                source.write_bytes(uploaded.getbuffer())
                info = inspect_video(source)
                radius = max(1, round(info["fps"] * {"Gentle": 0.2, "Balanced": 0.5, "Strong": 0.9}[strength]))
                output = work / "stabilized.mp4"
                side_by_side = work / "comparison.mp4" if comparison else None
                report = stabilize(source, output, radius=radius, zoom=1 + crop / 100,
                                   comparison=side_by_side, preserve_audio=sound, progress=update, max_zoom=maximum_zoom)
                encoded_source, encoded_output = work / "before.mp4", work / "after.mp4"
                encode_for_browser(source, encoded_source)
                bar.progress(0.90, text="Preparing stabilized playback…")
                encode_for_browser(output, encoded_output)
                comparison_bytes = None
                if comparison:
                    bar.progress(0.95, text="Preparing side-by-side download…")
                    encoded_comparison = work / "side-by-side.mp4"
                    encode_for_browser(side_by_side, encoded_comparison)
                    comparison_bytes = encoded_comparison.read_bytes()
                st.session_state["result"] = {
                    "before": encoded_source.read_bytes(), "after": encoded_output.read_bytes(),
                    "comparison": comparison_bytes, "report": report,
                    "name": Path(uploaded.name).stem,
                    "settings": (strength, crop, sound, comparison, maximum_zoom),
                }
            bar.empty()
        except (ValueError, OSError, RuntimeError) as error:
            logging.getLogger(__name__).exception("Video processing failed")
            bar.empty()
            if isinstance(error, ValueError) and "Audio muxing failed" not in str(error):
                st.error(str(error))
            else:
                st.error("We couldn't finish this clip. Try a shorter MP4, or turn off Keep audio and retry.")

    result = st.session_state.get("result")
    if result:
        st.success("Export ready.")
        if result["settings"] != (strength, crop, sound, comparison, maximum_zoom):
            st.info("These previews use your previous settings. Click Stabilize video to apply your changes.")
        before, after = st.columns(2)
        with before:
            st.markdown("**Original**")
            st.video(result["before"])
        with after:
            st.markdown("**Stabilized**")
            st.video(result["after"])
        report = result["report"]
        st.markdown(f'<p class="clip-details">{report["width"]} × {report["height"]} &nbsp;·&nbsp; '
                    f'{report["fps"]:g} FPS input &nbsp;·&nbsp; Processed in {report["seconds"]:.1f}s</p>',
                    unsafe_allow_html=True)
        st.download_button("Download stabilized video", result["after"],
                           file_name=result["name"] + "-stabilized.mp4", mime="video/mp4",
                           type="primary", on_click="ignore", use_container_width=True)
        if result["comparison"]:
            st.download_button("Download side-by-side video", result["comparison"],
                               file_name=result["name"] + "-comparison.mp4", mime="video/mp4", on_click="ignore")
        if report["tracking_failures"]:
            st.warning(f'{report["tracking_failures"]} frame transitions could not be tracked reliably. Check the preview before using the result.')
        if report["crop_limited_frames"]:
            st.caption(f'Framing preserved: stabilization was eased in {report["crop_limited_frames"]} frames to stay within the zoom limit.')
        if not report["audio_preserved"]:
            st.caption("The stabilized export is silent: the clip had no audio, or Keep audio was off.")
        st.caption("Previews play independently. Downloads include browser-compatible video and any retained audio.")
    elif not submitted:
        st.caption("Add a video to compare the original and stabilized versions here.")
        media = Path(__file__).resolve().parents[2] / "docs"
        real_sample = media / "real-demo.mp4"
        benchmark_sample = media / "synthetic-benchmark.mp4"
        sample = media / "demo.gif"
        if real_sample.is_file() or benchmark_sample.is_file():
            real_tab, benchmark_tab = st.tabs(["Real footage", "Synthetic benchmark"])
            with real_tab:
                if real_sample.is_file():
                    st.video(str(real_sample))
                    st.caption("Real handheld example: original left, SteadyFrame right. Footage: Peter Cooper Jr., CC0. Balanced settings; no added shake.")
            with benchmark_tab:
                if benchmark_sample.is_file():
                    st.video(str(benchmark_sample))
                    benchmark = json.loads((media / "synthetic-benchmark.json").read_text())
                    st.caption(f'Synthetic benchmark: {benchmark["jitter_reduction_percent"]:.2f}% measured jitter reduction. Exact evaluated frames from 1080p / 120 FPS input, shown at 4× slow motion. Original left, stabilized right.')
        elif sample.is_file():
            st.image(str(sample), caption="Example: synthetic shake. Original on the left, stabilized on the right.")

st.divider()
st.caption("Temporary video files are removed when processing finishes. Preview copies are kept for this session; restart the app to clear them.")
