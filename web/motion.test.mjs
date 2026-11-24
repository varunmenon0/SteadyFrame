import { test } from "node:test";
import assert from "node:assert/strict";
import {
  apply,
  compose,
  inverse,
  estimateSimilarity,
  planTransforms,
  identity,
} from "./motion.mjs";
const near = (a, b, tolerance = 1e-6) =>
  assert.ok(Math.abs(a - b) < tolerance, `${a} != ${b}`);
test("RANSAC recovers translation, rotation and scale among moving foreground outliers", () => {
  const expected = [1.01 * Math.cos(0.02), 1.01 * Math.sin(0.02), 12, -8],
    pairs = [];
  for (let i = 0; i < 80; i++) {
    const x = (i % 10) * 57,
      y = Math.floor(i / 10) * 39;
    pairs.push([x, y, ...apply(expected, x, y)]);
  }
  for (let i = 0; i < 25; i++)
    pairs.push([i * 11, i * 4, 700 - i * 17, 90 + i * 19]);
  const actual = estimateSimilarity(pairs);
  actual.forEach((v, i) => near(v, expected[i]));
  assert.equal(estimateSimilarity(pairs.slice(0, 4)), null);
});
test("composition and inversion preserve points", () => {
  const m = [1.02, 0.03, 11, -7],
    point = [450, 220];
  apply(compose(inverse(m), m), ...point).forEach((v, i) => near(v, point[i]));
});
test("smoothing reduces seeded jitter while every output corner remains inside its source", () => {
  const w = 960,
    h = 540;
  const frames = Array.from({ length: 120 }, (_, i) => ({
    pose: [1, 0, i * 0.2 + Math.sin(i * 2.1) * 9, Math.cos(i * 1.9) * 7],
    timestamp: i / 30,
    cut: false,
  }));
  const result = planTransforms(frames, w, h);
  let before = 0,
    after = 0;
  const original = frames.map((f) => apply(f.pose, w / 2, h / 2)),
    stabilized = result.map((r, i) =>
      apply(compose(r.matrix, frames[i].pose), w / 2, h / 2),
    );
  for (let i = 1; i < 119; i++)
    for (let j = 0; j < 2; j++) {
      before +=
        (original[i + 1][j] - 2 * original[i][j] + original[i - 1][j]) ** 2;
      after +=
        (stabilized[i + 1][j] - 2 * stabilized[i][j] + stabilized[i - 1][j]) **
        2;
    }
  assert.ok(after < before * 0.02, `Residual acceleration ${after / before}`);
  for (const frame of result) {
    assert.ok(frame.zoom <= 1.25 + 1e-6);
    for (const [x, y] of [
      [0, 0],
      [w, 0],
      [w, h],
      [0, h],
    ]) {
      const [u, v] = apply(inverse(frame.matrix), x, y);
      assert.ok(
        u >= 0.99 && u <= w - 0.99 && v >= 0.99 && v <= h - 0.99,
        `${u},${v}`,
      );
    }
  }
});
test("scene boundaries keep one shot from affecting another", () => {
  const first = Array.from({ length: 15 }, (_, i) => ({
    pose: [1, 0, i * 2, 0],
    timestamp: i / 30,
    cut: false,
  }));
  const second = Array.from({ length: 15 }, (_, i) => ({
    pose: identity(),
    timestamp: (i + 15) / 30,
    cut: i === 0,
  }));
  const combined = planTransforms([...first, ...second], 960, 540).slice(15);
  const alone = planTransforms(second, 960, 540);
  combined.forEach((f, i) =>
    f.matrix.forEach((v, j) => near(v, alone[i].matrix[j])),
  );
});
test("large rotations respect the crop budget without exposed borders", () => {
  const frames = Array.from({ length: 70 }, (_, i) => {
    const angle = Math.sin(i) * 0.2;
    return {
      pose: [
        Math.cos(angle),
        Math.sin(angle),
        Math.sin(i * 2) * 65,
        Math.cos(i) * 40,
      ],
      timestamp: i / 30,
      cut: false,
    };
  });
  for (const frame of planTransforms(frames, 3840, 2160, 0.5, 1.15)) {
    assert.ok(frame.zoom <= 1.1501, `Zoom ${frame.zoom}`);
    for (const [x, y] of [
      [0, 0],
      [3840, 0],
      [3840, 2160],
      [0, 2160],
    ]) {
      const [u, v] = apply(inverse(frame.matrix), x, y);
      assert.ok(u >= 0.99 && v >= 0.99 && u <= 3839.01 && v <= 2159.01);
    }
  }
});
