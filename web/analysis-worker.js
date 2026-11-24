/* OpenCV runs off the interface thread. Only one analysis frame is retained. */
let ready,
  previous,
  pose = [1, 0, 0, 0];
self.onmessage = async ({ data }) => {
  try {
    if (data.type === "init") {
      importScripts("./vendor/opencv.js");
      // OpenCV's Emscripten build exposes a thenable module.
      ready = new Promise((resolve) => {
        self.cv.then((module) => resolve({ module }));
      });
      const { module } = await ready;
      self.vision = module;
      self.motion = await import("./motion.mjs");
      self.postMessage({ ok: true });
      return;
    }
    const vision = self.vision,
      m = self.motion;
    const rgba = vision.matFromImageData(data.image),
      gray = new vision.Mat();
    vision.cvtColor(rgba, gray, vision.COLOR_RGBA2GRAY);
    rgba.delete();
    let cut = false,
      reliable = false;
    if (previous) {
      const histA = new Float64Array(32),
        histB = new Float64Array(32);
      let diff = 0,
        count = 0;
      const step = Math.max(1, Math.floor(gray.data.length / 14400));
      for (let i = 0; i < gray.data.length; i += step) {
        histA[previous.data[i] >> 3]++;
        histB[gray.data[i] >> 3]++;
        diff += Math.abs(previous.data[i] - gray.data[i]);
        count++;
      }
      let overlap = 0;
      for (let i = 0; i < 32; i++)
        overlap += Math.sqrt(histA[i] * histB[i]) / count;
      cut = Math.sqrt(Math.max(0, 1 - overlap)) > 0.65 && diff / count > 35;
      if (!cut) {
        const points = new vision.Mat(),
          next = new vision.Mat(),
          status = new vision.Mat(),
          err = new vision.Mat(),
          mask = new vision.Mat();
        try {
          vision.goodFeaturesToTrack(previous, points, 500, 0.01, 10, mask);
          if (points.rows >= 6) {
            vision.calcOpticalFlowPyrLK(
              previous,
              gray,
              points,
              next,
              status,
              err,
            );
            const pairs = [];
            for (let i = 0; i < points.rows; i++)
              if (status.data[i])
                pairs.push([
                  points.data32F[2 * i],
                  points.data32F[2 * i + 1],
                  next.data32F[2 * i],
                  next.data32F[2 * i + 1],
                ]);
            const delta = m.estimateSimilarity(pairs);
            if (delta) {
              delta[2] *= data.scale;
              delta[3] *= data.scale;
              pose = m.compose(delta, pose);
              reliable = true;
            }
          }
        } finally {
          for (const mat of [points, next, status, err, mask]) mat.delete();
        }
      } else pose = m.identity();
      previous.delete();
    }
    previous = gray;
    self.postMessage({ ok: true, pose, cut, reliable });
  } catch (error) {
    console.error(error);
    self.postMessage({ ok: false, error: String(error.message || error) });
  }
};
