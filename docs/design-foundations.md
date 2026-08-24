# AirGPT design foundations (2026-07-27)

Two new assets, served from `/ui/` and loaded by `index.html`:

| File | What it is |
|------|------------|
| `ui/motion.js` | Springs, gestures, momentum. `window.Motion`. |
| `ui/apple.css` | Material / type tokens and the accessibility overrides. |

They are **additive**. Nothing that already works was restyled. Surfaces adopt them one
at a time.

---

## Why springs, not transitions

The app ships 91 CSS transitions and 41 hand-tuned cubic-beziers. A CSS transition:

- cannot be caught and reversed mid-flight,
- cannot inherit the velocity of the finger that started it,
- animates from a *logical* value, not what is on screen.

That is why a sheet you grab halfway closed finishes closing before it reopens, and why
a flick feels like a click. A spring has no duration — only a position and a velocity —
so retargeting mid-motion is just assigning a new target.

**Rule: anything a finger can touch uses a spring. Everything else can stay a CSS
transition.**

```js
// Catchable, velocity-aware. Calling it again mid-flight retargets, it does not restart.
Motion.springTo(sheetEl, 0, { preset: 'sheet', velocity: releaseVelocity });
```

### Presets (the values Apple ships)

| Preset | damping | response | Use for |
|--------|---------|----------|---------|
| `ui` | 1.0 | 0.35 | default — **no overshoot** |
| `snappy` | 1.0 | 0.25 | small, frequent controls |
| `move` | 1.0 | 0.4 | repositioning |
| `rotate` | 0.8 | 0.4 | rotation |
| `sheet` | 0.8 | 0.3 | drawers, bottom sheets |

Bounce only where a gesture carried momentum. Overshoot on a menu that merely appeared
reads as sloppy; overshoot on a card you threw reads as physical.

### The gesture pipeline

```js
Motion.draggable(handle, {
  axis: 'y',
  getValue: () => currentOffset,
  onMove: ({ value }) => {
    // 1:1 with the finger, rubber-banded at the edges
    sheet.style.transform = `translate3d(0, ${Motion.withRubberband(value, 0, maxY, 400)}px, 0)`;
  },
  onEnd: ({ value, velocity, projected }) => {
    // Land where the flick was aimed, not where the finger happened to stop
    const target = Motion.nearestSnap(projected, [0, maxY]);
    Motion.springTo(sheet, target, { preset: 'sheet', velocity });
  },
});
```

`draggable` preserves the **grab offset** (the element does not jump to centre), uses
`setPointerCapture` (tracking survives leaving the element), and computes velocity from
a 100 ms window of samples rather than the last two events, which are mostly jitter.

`Motion.project(v)` is Apple's exponential decay `(v/1000)·d/(1−d)`, **not** the textbook
`v²/2a` — the textbook form decelerates too abruptly and a throw feels like it hit
something.

All of this is unit-tested headlessly: `node --test tests/motion.test.mjs` (15 tests).
The maths is testable; the feel is not, so the maths is what is pinned.

---

## Materials

`.mat-thin` / `.mat-regular` / `.mat-thick`. Weight encodes hierarchy — heavier
separates structural regions, lighter draws attention to interactive things. Never stack
a light material on another; legibility collapses. Bigger surfaces get more blur *and* a
deeper shadow.

Put `.on-material` on text over a translucent surface: flat grey text disappears over a
moving backdrop, so it goes slightly heavier with a touch more tracking.

`.scroll-edge-top` / `.scroll-edge-bottom` fade content where floating chrome overlaps
it. A hairline rule says "two boxes"; a fade says "one surface".

---

## Type

Tracking is **size-specific**. One `letter-spacing` for every size is wrong somewhere:
large text reads too loose as it grows, small text too tight. Use `.t-display`,
`.t-title`, `.t-body`, `.t-caption`, which pair tracking with the right leading.

---

## Accessibility — this part is global on purpose

Before this file, of 91 transitions and 39 backdrop-filters, **two** respected
`prefers-reduced-motion` and **none** respected reduced-transparency or increased
contrast. Those are correctness bugs for real users, so `apple.css` handles all three
app-wide:

- `prefers-reduced-motion` — keeps opacity/colour changes (they aid comprehension),
  removes travel, spring and parallax. Carries `!important` because it has to beat
  inline styles.
- `prefers-reduced-transparency` — frosts glass into a solid; drops the blur.
- `prefers-contrast: more` — solid backgrounds with a defined border.

`Motion.Spring` checks reduced-motion too and snaps straight to the target.

---

## Measured findings

**Touch targets.** At a 375×812 phone viewport, **201 controls render under 32px**, some
as small as 12×22 (`group-by-btn`, unlabelled icon buttons). Apple's minimum is 44pt.
Layout itself is clean — zero horizontal overflow.

`.hit-44` fixes one without changing how it looks: it pads the hit area via `::after` to
`max(100%, 44px)`. Verified — a 12×22 button becomes tappable ±18px from centre while its
painted size is unchanged.

This is deliberately *not* applied to all 201 yet. That is a broad sweep through a file
two people edit, and it should be one focused pass with someone watching the phone.

**Press feedback already exists.** `.btn`, `.icon-btn`, `.nav-item`, `.qr-btn` and
`.proj-page-card` already scale on `:active`. Adding `.press` to those is a no-op — use
it only on surfaces with no feedback at all (cards, chips, list rows).

---

## Adoption order

1. Bottom sheets / drawers on phone — biggest feel win, `draggable` + `sheet` preset.
2. The `.hit-44` sweep, on a real phone.
3. Modals → `.mat-thick` + scrim; side panels → `.mat-regular`, no scrim.
4. Headings → `.t-title` / `.t-display` to retire fixed letter-spacing.

Do not convert working CSS transitions on non-interactive things. Springs are for what
the user can touch.
