"""Local browser interface. Run with video-stabilizer-ui."""
import hashlib
import logging
from pathlib import Path
import tempfile

import streamlit as st

from video_stabilizer.core import stabilize
from video_stabilizer.web import encode_for_browser, inspect_video

st.set_page_config(page_title="Motion Lab · Video Stabilizer", page_icon="◈", layout="wide")
st.markdown("""
<style>
.block-container {max-width: 1250px; padding-top: 2.8rem;}
h1 {letter-spacing: -0.05em; font-weight: 750 !important;}
[data-testid="stMetric"] {border: 1px solid #294054; border-radius: 12px; padding: 14px;}
[data-testid="stMetricValue"] {font-size: 1.1rem;}
[data-testid="stToolbar"] {visibility: hidden;}
[data-testid="stForm"] {border-radius: 16px;}
.eyebrow {color: #5eead4; font-size: .78rem; letter-spacing: .18em; font-weight: 700;}
</style>
<div class="eyebrow">MOTION LAB / LOCAL VIDEO TOOLS</div>
""", unsafe_allow_html=True)
st.title("Less shake. More of the moment.")
st.write("Turn shaky footage into a smoother video. Upload a clip, tune the strength, and export your result.")
st.caption("Runs on this computer · No cloud upload · Up to 100 MB, 60 seconds, 1080p and 120 FPS input")

controls, workspace = st.columns([1, 2], gap="large")
with controls:
    st.subheader("01 / Your clip")
    uploaded = st.file_uploader("Choose a video", type=["mp4", "mov", "m4v", "avi", "mkv"],
                                help="Drop a video here or browse your files.")
    identity = hashlib.sha256(uploaded.getbuffer()).hexdigest() if uploaded else None
    if st.session_state.get("input_identity") != identity:
        st.session_state.pop("result", None)
        st.session_state["input_identity"] = identity
    with st.form("settings"):
        st.subheader("02 / Make it smoother")
        strength = st.select_slider("Stabilization strength", ["Gentle", "Balanced", "Strong"], value="Balanced")
        st.caption("Stronger smoothing removes more shake and can soften intentional camera movement.")
        crop = st.slider("Minimum crop", 0, 15, 5, format="%d%%",
                         help="A small crop hides moving borders. Extra cropping is added automatically when needed.")
        sound = st.checkbox("Keep audio", value=True)
        comparison = st.checkbox("Include side-by-side download", value=True)
        submitted = st.form_submit_button("Stabilize video", type="primary", disabled=uploaded is None,
                                          use_container_width=True)
    st.caption("Adaptive cropping is on. Your original file is never overwritten.")

with workspace:
    st.subheader("03 / Preview & export")
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
            with tempfile.TemporaryDirectory(prefix="motion-lab-") as directory:
                work = Path(directory)
                source = work / ("input" + Path(uploaded.name).suffix.lower())
                source.write_bytes(uploaded.getbuffer())
                info = inspect_video(source)
                radius = max(1, round(info["fps"] * {"Gentle": 0.2, "Balanced": 0.5, "Strong": 0.9}[strength]))
                output = work / "stabilized.mp4"
                side_by_side = work / "comparison.mp4" if comparison else None
                report = stabilize(source, output, radius=radius, zoom=1 + crop / 100,
                                   comparison=side_by_side, preserve_audio=sound, progress=update)
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
                    "settings": (strength, crop, sound, comparison),
                }
            bar.progress(1., text="Ready to preview and download")
        except (ValueError, OSError, RuntimeError) as error:
            logging.getLogger(__name__).exception("Video processing failed")
            bar.empty()
            if isinstance(error, ValueError) and "Audio muxing failed" not in str(error):
                st.error(str(error))
            else:
                st.error("We couldn't finish this clip. Try a shorter MP4, or turn off Keep audio and retry.")

    result = st.session_state.get("result")
    if result:
        st.success("Your stabilized video is ready.")
        if result["settings"] != (strength, crop, sound, comparison):
            st.info("These previews use your previous settings. Click Stabilize video to apply your changes.")
        before, after = st.columns(2)
        with before:
            st.markdown("**Original**")
            st.video(result["before"])
        with after:
            st.markdown("**Stabilized**")
            st.video(result["after"])
        report = result["report"]
        one, two, three = st.columns(3)
        one.metric("Resolution", f'{report["width"]} × {report["height"]}')
        two.metric("Input rate", f'{report["fps"]:g} FPS')
        three.metric("Processing", f'{report["seconds"]:.1f}s')
        st.download_button("Download stabilized video", result["after"],
                           file_name=result["name"] + "-stabilized.mp4", mime="video/mp4",
                           type="primary", on_click="ignore", use_container_width=True)
        if result["comparison"]:
            st.download_button("Download side-by-side video", result["comparison"],
                               file_name=result["name"] + "-comparison.mp4", mime="video/mp4", on_click="ignore")
        if report["tracking_failures"]:
            st.warning(f'{report["tracking_failures"]} frame transitions could not be tracked reliably. Check the preview before using the result.')
        if not report["audio_preserved"]:
            st.caption("The stabilized export is silent: the clip had no audio, or Keep audio was off.")
        st.caption("Previews play independently. Downloads include browser-compatible video and any retained audio.")
    elif not submitted:
        st.info("Choose a clip, then click Stabilize video. Your before-and-after previews will appear here.")
        sample = Path(__file__).resolve().parents[2] / "docs" / "demo.gif"
        if sample.is_file():
            with st.expander("See a synthetic before-and-after example", expanded=True):
                st.image(str(sample), caption="Generated translation and rotation shake. Original left, stabilized right.")

st.divider()
st.caption("Temporary video files are removed when processing finishes. Preview copies are kept for this session; restart the app to clear them.")
