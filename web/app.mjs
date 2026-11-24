import {
  Input,
  BlobSource,
  ALL_FORMATS,
  CanvasSink,
  CanvasSource,
  Output,
  Mp4OutputFormat,
  BufferTarget,
  EncodedPacketSink,
  EncodedAudioPacketSource,
} from "./vendor/mediabunny.mjs";
import { planTransforms } from "./motion.mjs";

const $ = (id) => document.getElementById(id);
let file, inputURL, resultURL, job;
const supported = !!(
  globalThis.VideoEncoder &&
  globalThis.VideoDecoder &&
  globalThis.OffscreenCanvas &&
  globalThis.Worker
);
$("unsupported").hidden = supported;
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
function status(message, error = false) {
  $("status").textContent = message;
  $("status").classList.toggle("error", error);
}
function tab(result) {
  $("original-tab").setAttribute("aria-selected", String(!result));
  $("result-tab").setAttribute("aria-selected", String(result));
  $("original-panel").hidden = result;
  $("result-panel").hidden = !result;
  $(result ? "original" : "result").pause();
}
$("original-tab").onclick = () => tab(false);
$("result-tab").onclick = () => tab(true);
function discardResult() {
  $("result").pause();
  $("result").removeAttribute("src");
  $("result").load();
  if (resultURL) URL.revokeObjectURL(resultURL);
  resultURL = null;
  $("download").hidden = true;
  $("result-tab").disabled = true;
  tab(false);
}
function selectFile(selected) {
  if (job || !selected) return;
  if (selected.size > 150 * 1024 * 1024) {
    status("Choose a video smaller than 150 MB.", true);
    return;
  }
  discardResult();
  if (inputURL) URL.revokeObjectURL(inputURL);
  file = selected;
  inputURL = URL.createObjectURL(file);
  $("original").src = inputURL;
  $("original").hidden = false;
  $("empty").hidden = true;
  $("filename").textContent = file.name;
  $("filehint").textContent =
    `${(file.size / 1024 / 1024).toFixed(1)} MB · click to replace`;
  $("run").disabled = !supported;
  $("video-info").textContent = "";
  status("Ready to stabilize.");
}
$("file").onchange = (e) => selectFile(e.target.files[0]);
for (const event of ["dragenter", "dragover"])
  $("dropzone").addEventListener(event, (e) => {
    e.preventDefault();
    if (!job) $("dropzone").classList.add("dragover");
  });
for (const event of ["dragleave", "drop"])
  $("dropzone").addEventListener(event, (e) => {
    e.preventDefault();
    $("dropzone").classList.remove("dragover");
    if (event === "drop") selectFile(e.dataTransfer.files[0]);
  });
$("smoothing").oninput = () => {
  $("smoothing-value").textContent =
    Number($("smoothing").value) === 0.5
      ? "Balanced"
      : `${Number($("smoothing").value).toFixed(1)} s`;
};
$("sample").onclick = async () => {
  $("sample").disabled = true;
  try {
    status("Loading the sample…");
    const r = await fetch("./media/sample-input.mp4");
    if (!r.ok) throw new Error("Sample could not be loaded.");
    selectFile(
      new File([await r.blob()], "sample-input.mp4", { type: "video/mp4" }),
    );
  } catch (e) {
    status(e.message, true);
  } finally {
    $("sample").disabled = false;
  }
};
function busy(value) {
  for (const id of ["file", "sample", "smoothing", "crop", "audio"])
    $(id).disabled = value;
  $("run").disabled = value || !file || !supported;
  $("cancel").hidden = !value;
  $("progress").hidden = !value;
}
function check(current) {
  if (current.cancelled) throw new DOMException("Cancelled", "AbortError");
}
function request(worker, data) {
  return new Promise((resolve, reject) => {
    worker.onmessage = ({ data }) =>
      data.ok ? resolve(data) : reject(new Error(data.error));
    worker.onerror = (e) =>
      reject(new Error(e.message || "The analysis worker stopped."));
    worker.postMessage(data, data.image ? [data.image.data.buffer] : []);
  });
}
$("cancel").onclick = () => {
  if (job) {
    job.cancelled = true;
    job.worker?.terminate();
    job.reject?.(new DOMException("Cancelled", "AbortError"));
    job.output?.cancel().catch(() => {});
    status("Cancelling…");
  }
};
async function workerRequest(current, data) {
  check(current);
  return Promise.race([
    request(current.worker, data),
    new Promise((_, reject) => (current.reject = reject)),
  ]).finally(() => (current.reject = null));
}
$("controls").onsubmit = async (event) => {
  event.preventDefault();
  if (!file || job || !supported) return;
  const current = { cancelled: false };
  job = current;
  busy(true);
  discardResult();
  $("progress").value = 0;
  let input,
    output,
    finished = false;
  try {
    status("Reading the video…");
    input = new Input({ source: new BlobSource(file), formats: ALL_FORMATS });
    const video = await input.getPrimaryVideoTrack();
    check(current);
    if (!video || !(await video.canDecode()))
      throw new Error(
        "This video codec cannot be decoded here. Try an H.264 MP4 in Chrome or Edge.",
      );
    const width = video.displayWidth,
      height = video.displayHeight;
    const start = await video.getFirstTimestamp(),
      end = await video.computeDuration(),
      duration = end - start;
    if (!(duration > 0) || duration > 30.05)
      throw new Error("Choose a clip up to 30 seconds long.");
    if (
      width < 32 ||
      height < 32 ||
      Math.max(width, height) > 4096 ||
      Math.min(width, height) > 2160
    )
      throw new Error(
        "Choose a video between 32 pixels and 4K (4096 × 2160, in either orientation).",
      );
    const stats = await video.computePacketStats(120),
      fps = stats.averagePacketRate || 30;
    const bitrate = Math.round(
      Math.min(
        50_000_000,
        Math.max(3_000_000, width * height * Math.max(30, fps) * 0.12),
      ),
    );
    const config = {
      codec: width * height > 1920 * 1080 ? "avc1.640033" : "avc1.64002a",
      width,
      height,
      bitrate,
      framerate: Math.min(120, Math.max(1, fps)),
    };
    if (!(await VideoEncoder.isConfigSupported(config)).supported)
      throw new Error(
        "Your device cannot export this resolution as H.264. Try a smaller clip or the desktop app.",
      );
    $("video-info").textContent =
      `${width} × ${height} · ${duration.toFixed(1)} s`;
    const format = new Mp4OutputFormat({ fastStart: "in-memory" });
    let audio = await input.getPrimaryAudioTrack(),
      audioSource,
      audioConfig;
    if (audio && $("audio").checked) {
      const codec = await audio.getCodec();
      if (!format.getSupportedAudioCodecs().includes(codec))
        throw new Error(
          "This audio format cannot be copied to MP4. Uncheck “Keep original audio” to export a silent video.",
        );
      audioConfig = await audio.getDecoderConfig();
      if (!audioConfig)
        throw new Error(
          "The audio track could not be read. Uncheck “Keep original audio” to continue.",
        );
      audioSource = new EncodedAudioPacketSource(codec);
    } else audio = null;
    status("Preparing motion analysis…");
    current.worker = new Worker("./analysis-worker.js");
    await workerRequest(current, { type: "init" });
    check(current);
    const aw = Math.round(width * Math.min(1, 960 / Math.max(width, height))),
      ah = Math.round(height * Math.min(1, 960 / Math.max(width, height)));
    const analysis = new CanvasSink(video, {
      width: aw,
      height: ah,
      fit: "fill",
      poolSize: 2,
    });
    const frames = [];
    for await (const frame of analysis.canvases()) {
      check(current);
      const image = frame.canvas
        .getContext("2d", { willReadFrequently: true })
        .getImageData(0, 0, aw, ah);
      const motion = await workerRequest(current, {
        type: "frame",
        image,
        scale: width / aw,
      });
      frames.push({
        pose: motion.pose,
        cut: motion.cut,
        reliable: motion.reliable,
        timestamp: frame.timestamp,
        duration: frame.duration,
      });
      $("progress").value = Math.min(
        50,
        (50 * (frame.timestamp - start)) / duration,
      );
      status(`Analyzing camera movement… ${frames.length} frames`);
      if (frames.length > 4000)
        throw new Error(
          "This clip has too many frames for the browser demo. Choose a shorter excerpt.",
        );
    }
    current.worker.terminate();
    current.worker = null;
    check(current);
    const tracked = frames.slice(1).filter((f) => f.reliable || f.cut).length;
    if (frames.length < 2 || tracked < Math.max(1, (frames.length - 1) * 0.3))
      throw new Error(
        "Too few stable details to track in this clip. Try footage with a clearer background.",
      );
    status("Smoothing the camera path…");
    await tick();
    const transforms = planTransforms(
      frames,
      width,
      height,
      Number($("smoothing").value),
      Number($("crop").value),
    );
    check(current);
    const canvas = new OffscreenCanvas(width, height),
      ctx = canvas.getContext("2d", { alpha: false });
    output = new Output({ format, target: new BufferTarget() });
    current.output = output;
    const source = new CanvasSource(canvas, { codec: "avc", bitrate });
    output.addVideoTrack(source);
    if (audioSource) output.addAudioTrack(audioSource);
    await output.start();
    check(current);
    const copyAudio = async () => {
      if (!audioSource) return;
      try {
        const packets = new EncodedPacketSink(audio);
        for await (const packet of packets.packets()) {
          check(current);
          if (packet.timestamp >= end) break;
          if (packet.timestamp + packet.duration <= start) continue;
          await audioSource.add(
            packet.clone({ timestamp: packet.timestamp - start }),
            { decoderConfig: audioConfig },
          );
        }
      } finally {
        audioSource.close();
      }
    };
    const render = async () => {
      try {
        let i = 0;
        const full = new CanvasSink(video, { poolSize: 2 });
        for await (const frame of full.canvases()) {
          check(current);
          const transform = transforms[i];
          if (
            !transform ||
            Math.abs(frame.timestamp - transform.timestamp) > 0.0001
          )
            throw new Error(
              "The decoded frame order changed. Please try the clip again.",
            );
          const [a, b, x, y] = transform.matrix;
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          ctx.fillStyle = "#000";
          ctx.fillRect(0, 0, width, height);
          ctx.setTransform(a, b, -b, a, x, y);
          ctx.drawImage(frame.canvas, 0, 0, width, height);
          await source.add(frame.timestamp - start, frame.duration, {
            keyFrame: i % Math.max(1, Math.round(fps * 2)) === 0,
          });
          i++;
          $("progress").value =
            50 + Math.min(49, (49 * (frame.timestamp - start)) / duration);
          status(
            `Exporting MP4… ${Math.round((100 * i) / transforms.length)}%`,
          );
          await tick();
        }
        if (i !== transforms.length)
          throw new Error("The exported frame count did not match the source.");
      } finally {
        source.close();
      }
    };
    const streams = [render(), copyAudio()];
    try {
      await Promise.all(streams);
    } catch (error) {
      current.cancelled = true;
      await output.cancel().catch(() => {});
      await Promise.allSettled(streams);
      throw error;
    }
    check(current);
    status("Finishing the file…");
    await output.finalize();
    check(current);
    finished = true;
    resultURL = URL.createObjectURL(
      new Blob([output.target.buffer], { type: "video/mp4" }),
    );
    $("result").src = resultURL;
    $("result-tab").disabled = false;
    $("download").href = resultURL;
    $("download").download =
      `${file.name.replace(/\.[^.]+$/, "")}-steadyframe.mp4`;
    $("download").hidden = false;
    const max = Math.max(...transforms.map((t) => t.zoom));
    status(
      `Done · ${frames.length} frames · up to ${max.toFixed(2)}× crop${audioSource ? " · original audio" : ""}`,
    );
    $("progress").value = 100;
    tab(true);
  } catch (error) {
    status(
      error.name === "AbortError"
        ? "Cancelled. Your original video is ready to try again."
        : error.message || "Something went wrong. Please try another clip.",
      error.name !== "AbortError",
    );
  } finally {
    current.worker?.terminate();
    if (output && !finished) await output.cancel().catch(() => {});
    input?.dispose();
    job = null;
    busy(false);
  }
};
window.addEventListener("beforeunload", () => {
  if (inputURL) URL.revokeObjectURL(inputURL);
  if (resultURL) URL.revokeObjectURL(resultURL);
  job?.worker?.terminate();
});
