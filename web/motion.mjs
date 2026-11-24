// Similarities use [a, b, tx, ty]: x' = ax - by + tx; y' = bx + ay + ty.
export const identity = () => [1, 0, 0, 0];
export const apply = (m, x, y) => [
  m[0] * x - m[1] * y + m[2],
  m[1] * x + m[0] * y + m[3],
];
export function compose(p, q) {
  const t = apply(p, q[2], q[3]);
  return [p[0] * q[0] - p[1] * q[1], p[1] * q[0] + p[0] * q[1], ...t];
}
export function inverse(m) {
  const d = m[0] ** 2 + m[1] ** 2;
  if (d < 1e-12) throw new Error("Degenerate motion estimate");
  return [
    m[0] / d,
    -m[1] / d,
    -(m[0] * m[2] + m[1] * m[3]) / d,
    (m[1] * m[2] - m[0] * m[3]) / d,
  ];
}
function fit(points) {
  const n = points.length;
  const sums = points.reduce((a, p) => a.map((v, i) => v + p[i]), [0, 0, 0, 0]);
  const [x, y, u, v] = sums.map((s) => s / n);
  let d = 0,
    a = 0,
    b = 0;
  for (const [px, py, pu, pv] of points) {
    const dx = px - x,
      dy = py - y;
    d += dx * dx + dy * dy;
    a += dx * (pu - u) + dy * (pv - v);
    b += dx * (pv - v) - dy * (pu - u);
  }
  if (d < 1e-6) return null;
  a /= d;
  b /= d;
  if (Math.hypot(a, b) < 1e-6) return null;
  return [a, b, u - a * x + b * y, v - b * x - a * y];
}
export function estimateSimilarity(points, threshold = 3) {
  if (points.length < 6) return null;
  let seed = 2026,
    best = [];
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  for (let i = 0; i < 160; i++) {
    const p = points[Math.floor(random() * points.length)],
      q = points[Math.floor(random() * points.length)];
    const m = fit([p, q]);
    if (!m) continue;
    const inliers = points.filter(([x, y, u, v]) => {
      const [a, b] = apply(m, x, y);
      return (a - u) ** 2 + (b - v) ** 2 <= threshold ** 2;
    });
    if (inliers.length > best.length) best = inliers;
  }
  return best.length >= Math.max(6, points.length * 0.3) ? fit(best) : null;
}
function smooth(values, radius) {
  const sums = [0];
  for (const x of values) sums.push(sums.at(-1) + x);
  return values.map((_, i) => {
    const l = Math.max(0, i - radius),
      r = Math.min(values.length - 1, i + radius);
    return (
      (sums[r + 1] -
        sums[l] +
        Math.max(0, radius - i) * values[0] +
        Math.max(0, i + radius - values.length + 1) * values.at(-1)) /
      (radius * 2 + 1)
    );
  });
}
function blend(m, amount, w, h) {
  const angle = Math.atan2(m[1], m[0]) * amount,
    scale = Math.hypot(m[0], m[1]) ** amount;
  const a = Math.cos(angle) * scale,
    b = Math.sin(angle) * scale,
    [x, y] = apply(m, w / 2, h / 2);
  return [
    a,
    b,
    w / 2 + amount * (x - w / 2) - (a * w) / 2 + (b * h) / 2,
    h / 2 + amount * (y - h / 2) - (b * w) / 2 - (a * h) / 2,
  ];
}
export function crop(m, w, h, minZoom = 1.04, center = [w / 2, h / 2]) {
  const inv = inverse(m),
    inside = (x, y) => {
      const [u, v] = apply(inv, x, y);
      return u >= 1 && v >= 1 && u <= w - 1 && v <= h - 1;
    };
  let [cx, cy] = center;
  if (!inside(cx, cy)) [cx, cy] = apply(m, w / 2, h / 2);
  let low = 0,
    high = Math.hypot(m[0], m[1]) / minZoom;
  for (let i = 0; i < 30; i++) {
    const k = (low + high) / 2;
    const ok = [
      [-1, -1],
      [1, -1],
      [1, 1],
      [-1, 1],
    ].every(([x, y]) => inside(cx + (x * w * k) / 2, cy + (y * h * k) / 2));
    if (ok) low = k;
    else high = k;
  }
  const s = 1 / Math.max(low, 1e-8);
  return {
    matrix: compose([s, 0, w / 2 - s * cx, h / 2 - s * cy], m),
    zoom: s * Math.hypot(m[0], m[1]),
  };
}
export function planTransforms(frames, w, h, seconds = 0.5, maxZoom = 1.25) {
  if (!frames.length) throw new Error("No video frames were decoded.");
  const result = [];
  for (let start = 0; start < frames.length; ) {
    let end = start + 1;
    while (end < frames.length && !frames[end].cut) end++;
    const shot = frames.slice(start, end),
      n = shot.length;
    const fps =
      n > 1
        ? (n - 1) / Math.max(0.001, shot.at(-1).timestamp - shot[0].timestamp)
        : 30;
    const radius = Math.max(1, Math.round(seconds * fps)),
      paths = [[], [], [], []];
    let prevAngle = 0;
    for (const { pose: m } of shot) {
      let angle = Math.atan2(m[1], m[0]);
      while (angle - prevAngle > Math.PI) angle -= Math.PI * 2;
      while (angle - prevAngle < -Math.PI) angle += Math.PI * 2;
      prevAngle = angle;
      [m[2], m[3], angle, Math.log(Math.hypot(m[0], m[1]))].forEach((v, i) =>
        paths[i].push(v),
      );
    }
    const target = paths.map((v) => smooth(v, radius));
    const corrections = shot.map(({ pose }, i) => {
      const s = Math.exp(target[3][i]),
        a = target[2][i];
      return compose(
        [s * Math.cos(a), s * Math.sin(a), target[0][i], target[1][i]],
        inverse(pose),
      );
    });
    const centers = corrections.map((m) => {
      const [x, y] = apply(m, w / 2, h / 2);
      return [w / 2 + 0.1 * (x - w / 2), h / 2 + 0.1 * (y - h / 2)];
    });
    const xs = smooth(
        centers.map((c) => c[0]),
        Math.round(fps * 0.25),
      ),
      ys = smooth(
        centers.map((c) => c[1]),
        Math.round(fps * 0.25),
      );
    const evaluate = (i, strength) =>
      crop(blend(corrections[i], strength, w, h), w, h, 1.04, [
        w / 2 + (xs[i] - w / 2) * strength,
        h / 2 + (ys[i] - h / 2) * strength,
      ]);
    const strengths = corrections.map((_, i) => {
      if (evaluate(i, 1).zoom <= maxZoom) return 1;
      let l = 0,
        r = 1;
      for (let j = 0; j < 22; j++) {
        const mid = (l + r) / 2;
        if (evaluate(i, mid).zoom <= maxZoom) l = mid;
        else r = mid;
      }
      return l;
    });
    for (let i = 1; i < n; i++)
      strengths[i] = Math.min(strengths[i], strengths[i - 1] + 0.5 / fps);
    for (let i = n - 2; i >= 0; i--)
      strengths[i] = Math.min(strengths[i], strengths[i + 1] + 0.5 / fps);
    const crops = strengths.map((s, i) => evaluate(i, s)),
      zooms = crops.map((c) => c.zoom);
    for (let i = 1; i < n; i++)
      zooms[i] = Math.max(zooms[i], zooms[i - 1] - 0.15 / fps);
    for (let i = n - 2; i >= 0; i--)
      zooms[i] = Math.max(zooms[i], zooms[i + 1] - 0.15 / fps);
    crops.forEach((c, i) => {
      const extra = zooms[i] / c.zoom;
      result.push({
        ...shot[i],
        matrix: compose(
          [extra, 0, (w / 2) * (1 - extra), (h / 2) * (1 - extra)],
          c.matrix,
        ),
        zoom: zooms[i],
      });
    });
    start = end;
  }
  return result;
}
