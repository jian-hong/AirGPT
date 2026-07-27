/**
 * AirGPT fluid motion — springs, gestures, momentum.
 *
 * Everything in AirGPT's UI today is a CSS transition: 91 of them, 41 hand-tuned
 * cubic-beziers. A CSS transition cannot be grabbed mid-flight, cannot inherit the
 * velocity of the finger that started it, and always animates from a *logical* value
 * rather than what is actually on screen. That is why a sheet the user catches halfway
 * closed finishes closing before it reopens, and why a flick feels like a click.
 *
 * A spring fixes all three at once, because it has no duration: it has a position and
 * a velocity, and re-targeting it mid-motion is just assigning a new target. That is
 * the whole reason Apple builds fluid interfaces on springs, and the reason this file
 * exists.
 *
 * Parameterised the way Apple exposes it to designers, not the way physics textbooks
 * write it:
 *   damping  — 1.0 settles with no overshoot; below 1.0 bounces. Default 1.0.
 *   response — seconds to substantially reach the target. Lower is snappier.
 *
 * Loads as a plain script (window.Motion) and as a CommonJS module so the maths can be
 * unit-tested in node without a browser.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.Motion = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // -- Presets Apple actually ships -----------------------------------------
  // Bounce only where a real gesture carried momentum. Overshoot on a menu that
  // merely appeared reads as sloppy; overshoot on a card you threw reads as physical.
  const PRESETS = {
    ui: { damping: 1.0, response: 0.35 },      // default: no overshoot
    move: { damping: 1.0, response: 0.4 },     // reposition (PiP-style)
    rotate: { damping: 0.8, response: 0.4 },
    sheet: { damping: 0.8, response: 0.3 },    // drawers, bottom sheets
    snappy: { damping: 1.0, response: 0.25 },
  };

  const REST_DELTA = 0.01;   // px — below one CSS pixel, nobody can see it move
  const REST_SPEED = 0.05;   // px/ms

  function prefersReducedMotion() {
    try {
      return (
        typeof matchMedia === "function" &&
        matchMedia("(prefers-reduced-motion: reduce)").matches
      );
    } catch (e) {
      return false;
    }
  }

  /**
   * Where a flick comes to rest.
   *
   * Apple's exponential-decay projection from the Designing Fluid Interfaces sample —
   * NOT the textbook v²/(2a), which decelerates too abruptly and makes a throw feel
   * like it hit something. Feed the result to nearestSnap() so a flick lands on the
   * target it was aimed at rather than the one it happened to be nearest on release.
   *
   * @param {number} velocity px/s at release
   * @param {number} decelerationRate 0.998 scroll-like, 0.99 snappier
   */
  function project(velocity, decelerationRate = 0.998) {
    if (!isFinite(velocity) || velocity === 0) return 0;
    const d = Math.min(Math.max(decelerationRate, 0), 0.9999);
    return ((velocity / 1000) * d) / (1 - d);
  }

  /**
   * Progressive resistance past a boundary. A hard stop reads as "frozen"; resistance
   * reads as "responsive, but there is nothing more here".
   */
  function rubberband(overshoot, dimension, constant = 0.55) {
    if (!dimension) return 0;
    return (
      (overshoot * dimension * constant) /
      (dimension + constant * Math.abs(overshoot))
    );
  }

  function nearestSnap(value, points) {
    if (!points || !points.length) return value;
    let best = points[0];
    let bestD = Math.abs(value - best);
    for (const p of points) {
      const d = Math.abs(value - p);
      if (d < bestD) {
        best = p;
        bestD = d;
      }
    }
    return best;
  }

  /** Clamp with rubber-band beyond the range — for live drag tracking. */
  function withRubberband(value, min, max, dimension) {
    if (value < min) return min - rubberband(min - value, dimension);
    if (value > max) return max + rubberband(value - max, dimension);
    return value;
  }

  /**
   * A spring with a position and a velocity. No duration, so it is interruptible by
   * construction: `setTarget` while it is moving keeps the current value and velocity
   * and simply pulls toward somewhere new. No jump, no "brick wall" at a reversal.
   */
  class Spring {
    constructor(options = {}) {
      const preset = PRESETS[options.preset] || PRESETS.ui;
      this.damping = options.damping != null ? options.damping : preset.damping;
      this.response = options.response != null ? options.response : preset.response;
      this.value = options.from || 0;
      this.velocity = options.velocity || 0;
      this.target = options.to != null ? options.to : this.value;
      this.onUpdate = options.onUpdate || null;
      this.onRest = options.onRest || null;
      this._raf = 0;
      this._last = 0;
      this._running = false;
    }

    setTarget(target, opts = {}) {
      this.target = target;
      // Velocity is *added*, not replaced: a gesture handing off into an in-flight
      // spring should blend, otherwise the motion visibly discontinues.
      if (opts.velocity != null) {
        this.velocity = opts.blend === false
          ? opts.velocity
          : this.velocity + opts.velocity;
      }
      if (opts.damping != null) this.damping = opts.damping;
      if (opts.response != null) this.response = opts.response;
      this.start();
      return this;
    }

    /** Jump with no animation — reduced motion, or a hard reset. */
    snapTo(value) {
      this.stop();
      this.value = this.target = value;
      this.velocity = 0;
      if (this.onUpdate) this.onUpdate(this.value, this);
      if (this.onRest) this.onRest(this.value, this);
      return this;
    }

    /** Advance the simulation by dt milliseconds. Pure — safe to test headlessly. */
    step(dtMs) {
      const omega = (2 * Math.PI) / Math.max(this.response, 0.0001);
      const zeta = Math.max(this.damping, 0);
      // Sub-step so a dropped frame cannot make the integrator explode.
      let remaining = Math.min(dtMs, 64);
      const maxStep = 4; // ms
      while (remaining > 0) {
        const h = Math.min(remaining, maxStep) / 1000;
        const displacement = this.value - this.target;
        const accel = -omega * omega * displacement - 2 * zeta * omega * this.velocity;
        this.velocity += accel * h;
        this.value += this.velocity * h;
        remaining -= maxStep;
      }
      return this.isAtRest();
    }

    isAtRest() {
      return (
        Math.abs(this.value - this.target) < REST_DELTA &&
        Math.abs(this.velocity) < REST_SPEED * 1000
      );
    }

    start() {
      if (this._running) return this;
      if (prefersReducedMotion()) return this.snapTo(this.target);
      this._running = true;
      this._last = 0;
      const tick = (now) => {
        if (!this._running) return;
        const dt = this._last ? now - this._last : 16;
        this._last = now;
        const rested = this.step(dt);
        if (this.onUpdate) this.onUpdate(this.value, this);
        if (rested) {
          this.value = this.target;
          this.velocity = 0;
          this._running = false;
          if (this.onUpdate) this.onUpdate(this.value, this);
          if (this.onRest) this.onRest(this.value, this);
          return;
        }
        this._raf = requestAnimationFrame(tick);
      };
      this._raf = requestAnimationFrame(tick);
      return this;
    }

    stop() {
      this._running = false;
      if (this._raf) cancelAnimationFrame(this._raf);
      this._raf = 0;
      return this;
    }
  }

  /**
   * 1:1 pointer dragging with capture, grab-offset and a velocity history.
   *
   * Two details that make or break the feel:
   *  - the grab offset is preserved, so the element does not jump to centre on grab;
   *  - velocity comes from a short window of recent samples, not the last two events,
   *    because a single pair is dominated by jitter at the moment of release.
   */
  function draggable(el, options = {}) {
    const axis = options.axis || "y";
    const onStart = options.onStart || null;
    const onMove = options.onMove || null;
    const onEnd = options.onEnd || null;
    const VELOCITY_WINDOW_MS = 100;

    let samples = [];
    let grabOffset = 0;
    let active = false;
    let startValue = 0;

    const coord = (e) => (axis === "x" ? e.clientX : e.clientY);

    function velocity() {
      if (samples.length < 2) return 0;
      const last = samples[samples.length - 1];
      let first = samples[0];
      for (const s of samples) {
        if (last.t - s.t <= VELOCITY_WINDOW_MS) {
          first = s;
          break;
        }
      }
      const dt = last.t - first.t;
      if (dt <= 0) return 0;
      return ((last.p - first.p) / dt) * 1000; // px/s
    }

    function down(e) {
      if (e.button != null && e.button !== 0) return;
      active = true;
      startValue = options.getValue ? options.getValue() : 0;
      grabOffset = coord(e) - startValue;
      samples = [{ p: coord(e), t: e.timeStamp || performance.now() }];
      try {
        el.setPointerCapture(e.pointerId);
      } catch (err) {
        /* capture is best-effort */
      }
      if (onStart) onStart({ value: startValue, event: e });
    }

    function move(e) {
      if (!active) return;
      const p = coord(e);
      samples.push({ p, t: e.timeStamp || performance.now() });
      if (samples.length > 12) samples.shift();
      if (onMove) onMove({ value: p - grabOffset, delta: p - grabOffset - startValue, event: e });
    }

    function up(e) {
      if (!active) return;
      active = false;
      const v = velocity();
      try {
        el.releasePointerCapture(e.pointerId);
      } catch (err) {
        /* already released */
      }
      if (onEnd) {
        onEnd({
          value: coord(e) - grabOffset,
          velocity: v,
          projected: coord(e) - grabOffset + project(v),
          event: e,
        });
      }
      samples = [];
    }

    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);

    return function destroy() {
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
    };
  }

  /**
   * Spring a single transform axis on an element. Reuses the live spring when one is
   * already attached, so a second call mid-flight retargets instead of restarting —
   * the difference between catching a moving panel and fighting it.
   */
  const _springs = new WeakMap();
  function springTo(el, to, options = {}) {
    const axis = options.axis || "y";
    const key = axis;
    let map = _springs.get(el);
    if (!map) {
      map = {};
      _springs.set(el, map);
    }
    let sp = map[key];
    const apply = (v) => {
      el.style.transform =
        axis === "x" ? `translate3d(${v}px,0,0)` : `translate3d(0,${v}px,0)`;
    };
    if (!sp) {
      sp = new Spring({
        preset: options.preset || "ui",
        damping: options.damping,
        response: options.response,
        from: options.from || 0,
        onUpdate: apply,
        onRest: options.onRest,
      });
      map[key] = sp;
    } else if (options.onRest) {
      sp.onRest = options.onRest;
    }
    sp.setTarget(to, {
      velocity: options.velocity,
      blend: options.blend,
      damping: options.damping,
      response: options.response,
    });
    return sp;
  }

  return {
    PRESETS,
    Spring,
    project,
    rubberband,
    nearestSnap,
    withRubberband,
    draggable,
    springTo,
    prefersReducedMotion,
    REST_DELTA,
    REST_SPEED,
  };
});
