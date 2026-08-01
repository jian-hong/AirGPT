/**
 * Physics tests for ui/motion.js.
 *
 * Feel is subjective; the maths underneath is not. A spring that overshoots when it
 * claims to be critically damped, or a projection that lands a flick in the wrong
 * place, is wrong in a way nobody notices until the interface feels cheap. Run with:
 *   node --test tests/motion.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const Motion = require("../ui/motion.js");

/** Run a spring to rest headlessly at a fixed timestep; report the path it took. */
function simulate(spring, { dt = 16, maxMs = 8000 } = {}) {
  const samples = [];
  let t = 0;
  while (t < maxMs) {
    spring.step(dt);
    samples.push({ t, value: spring.value, velocity: spring.velocity });
    if (spring.isAtRest()) break;
    t += dt;
  }
  return { samples, settleMs: t, rested: spring.isAtRest() };
}

test("critically damped spring never overshoots its target", () => {
  const s = new Motion.Spring({ damping: 1.0, response: 0.35, from: 0, to: 100 });
  s.target = 100;
  const { samples, rested } = simulate(s);
  assert.ok(rested, "spring never settled");
  const maxValue = Math.max(...samples.map((x) => x.value));
  assert.ok(maxValue <= 100.5, `overshot to ${maxValue} with damping 1.0`);
});

test("under-damped spring does overshoot, and still settles", () => {
  const s = new Motion.Spring({ damping: 0.6, response: 0.35, from: 0, to: 100 });
  s.target = 100;
  const { samples, rested } = simulate(s);
  assert.ok(rested, "bouncy spring never settled");
  const maxValue = Math.max(...samples.map((x) => x.value));
  assert.ok(maxValue > 100, `damping 0.6 should overshoot, peaked at ${maxValue}`);
});

test("lower response settles sooner", () => {
  const fast = new Motion.Spring({ damping: 1.0, response: 0.2, from: 0, to: 100 });
  fast.target = 100;
  const slow = new Motion.Spring({ damping: 1.0, response: 0.6, from: 0, to: 100 });
  slow.target = 100;
  assert.ok(
    simulate(fast).settleMs < simulate(slow).settleMs,
    "response is not controlling settle time",
  );
});

test("a spring is interruptible: retargeting mid-flight keeps position continuous", () => {
  const s = new Motion.Spring({ damping: 1.0, response: 0.4, from: 0, to: 300 });
  s.target = 300;
  for (let i = 0; i < 8; i++) s.step(16);
  const beforeValue = s.value;
  assert.ok(beforeValue > 0 && beforeValue < 300, "spring should be mid-flight");

  s.setTargetForTest = null;
  s.target = 0; // user grabbed it and threw it back
  s.step(16);
  // The defining property: no jump. It continues from where it visibly was.
  assert.ok(
    Math.abs(s.value - beforeValue) < 20,
    `value jumped ${beforeValue} -> ${s.value} on reversal`,
  );
});

test("reversal carries velocity through instead of hitting a brick wall", () => {
  const s = new Motion.Spring({ damping: 1.0, response: 0.4, from: 0, to: 300 });
  s.target = 300;
  for (let i = 0; i < 8; i++) s.step(16);
  const vBefore = s.velocity;
  assert.ok(vBefore > 0, "should be travelling toward the target");
  s.target = 0;
  s.step(16);
  // Velocity decays through zero rather than flipping sign instantly.
  assert.ok(s.velocity > 0 || Math.abs(s.velocity) < Math.abs(vBefore),
    "velocity was hard-cut at the reversal");
});

test("a spring already at its target does no work", () => {
  const s = new Motion.Spring({ damping: 1.0, response: 0.35, from: 42, to: 42 });
  s.target = 42;
  assert.equal(s.isAtRest(), true);
  s.step(16);
  assert.equal(s.value, 42);
});

test("survives a dropped frame without exploding", () => {
  const s = new Motion.Spring({ damping: 1.0, response: 0.3, from: 0, to: 100 });
  s.target = 100;
  s.step(2000); // tab was backgrounded
  assert.ok(Number.isFinite(s.value), "value went non-finite");
  assert.ok(Math.abs(s.value) < 1000, `value diverged to ${s.value}`);
});

test("project uses exponential decay, not the textbook formula", () => {
  // Apple's sample code: (v/1000) * d / (1 - d)
  const v = 1000; // px/s
  assert.ok(Math.abs(Motion.project(v, 0.998) - 499) < 1, Motion.project(v, 0.998));
  // A snappier deceleration rate must travel less far.
  assert.ok(Motion.project(v, 0.99) < Motion.project(v, 0.998));
});

test("project is signed and zero-safe", () => {
  assert.equal(Motion.project(0), 0);
  assert.ok(Motion.project(-500) < 0, "a leftward flick must project leftward");
  assert.equal(Motion.project(NaN), 0);
});

test("a flick lands on the target it was aimed at, not the nearest one", () => {
  const snaps = [0, 400];
  const position = 60;          // barely moved, so nearest is 0
  const velocity = 900;         // but thrown hard toward 400
  const naive = Motion.nearestSnap(position, snaps);
  const projected = Motion.nearestSnap(position + Motion.project(velocity), snaps);
  assert.equal(naive, 0, "fixture assumes the nearest snap is the wrong answer");
  assert.equal(projected, 400, "momentum projection did not carry the flick");
});

test("rubberband resists progressively and never fully stops", () => {
  const dim = 400;
  const a = Motion.rubberband(50, dim);
  const b = Motion.rubberband(200, dim);
  const c = Motion.rubberband(800, dim);
  assert.ok(a < b && b < c, "further drag must still move further");
  assert.ok(a / 50 > b / 200, "resistance must increase with distance");
  assert.ok(c < 800, "rubberband must damp, not pass through");
});

test("withRubberband is exact inside the bounds and soft outside", () => {
  assert.equal(Motion.withRubberband(50, 0, 100, 400), 50);
  assert.equal(Motion.withRubberband(0, 0, 100, 400), 0);
  const over = Motion.withRubberband(180, 0, 100, 400);
  assert.ok(over > 100 && over < 180, `expected damped overshoot, got ${over}`);
  const under = Motion.withRubberband(-80, 0, 100, 400);
  assert.ok(under < 0 && under > -80, `expected damped undershoot, got ${under}`);
});

test("presets match the values Apple ships", () => {
  assert.deepEqual(Motion.PRESETS.move, { damping: 1.0, response: 0.4 });
  assert.deepEqual(Motion.PRESETS.rotate, { damping: 0.8, response: 0.4 });
  assert.deepEqual(Motion.PRESETS.sheet, { damping: 0.8, response: 0.3 });
  assert.equal(Motion.PRESETS.ui.damping, 1.0, "the default must not bounce");
});

test("velocity handoff makes a released drag continue, not restart", () => {
  const withHandoff = new Motion.Spring({ damping: 1.0, response: 0.4, from: 0, to: 200 });
  withHandoff.target = 200;
  withHandoff.velocity = 1200; // finger was moving fast at release
  const cold = new Motion.Spring({ damping: 1.0, response: 0.4, from: 0, to: 200 });
  cold.target = 200;

  withHandoff.step(16);
  cold.step(16);
  assert.ok(
    withHandoff.value > cold.value,
    "released velocity did not carry into the animation",
  );
});

test("nearestSnap handles the degenerate cases", () => {
  assert.equal(Motion.nearestSnap(10, []), 10);
  assert.equal(Motion.nearestSnap(10, [10]), 10);
  assert.equal(Motion.nearestSnap(5, [0, 10]), 0, "ties resolve to the first point");
});
