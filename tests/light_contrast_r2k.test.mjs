/**
 * Light theme: dark-only colours that sat on a light surface (round 2 findings). The page's own
 * <style> and linked /ui/*.css are loaded into Chromium with stand-in markup, backgrounds are
 * composited with their transparency, and the ratio is computed.   node --test tests/light_contrast_r2k.test.mjs
 */
import { test, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright");
const root = new URL("../", import.meta.url);
const html = fs.readFileSync(new URL("index.html", root), "utf8");
const head = html.slice(0, html.indexOf("</head>"));
const inline = [...head.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]).join("\n");
const linked = [...head.matchAll(/<link rel="stylesheet" href="\/(ui\/[^"]+\.css)"/g)].map((m) => fs.readFileSync(new URL(m[1], root), "utf8")).join("\n");
let browser;
after(async () => { await browser?.close(); });

const BODY = `<div class="app"><button class="side-collapse-btn" id="scb" style="position:static;transform:none">›</button></div>
<section class="forge-shell" style="height:auto"><div class="forge-left"><h2 id="fh2">OpenForge</h2><p class="cortex-tag" id="ftag">Chat → chip</p>
<div class="forge-honesty"><span class="ok" id="fok">ngspice on PATH</span><span class="warn" id="fwarn">vendor not vendored</span></div>
<h3 id="frecent" style="color:var(--muted)">Recent designs</h3><p class="hint" id="fhint">No designs yet</p></div>
<aside class="forge-right"><h3 id="fr3" style="color:var(--muted)">Schematic · netlist</h3><div class="forge-schematic"><p class="hint" id="fout">Run a design</p></div></aside></section>
<div class="plus-menu open" id="pm"><button type="button"><span class="pm-check" id="pmc">✓</span> Thinking</button></div>
<span class="mp-creator"><i class="mp-logo" id="mpl">Q</i></span>
<div class="composer"><button class="cprefs-btn" id="cpb" disabled><span class="cprefs-label" id="cpl">Instructions</span></button></div>`;

const RATIO = (sel, kind) => `(() => {
  const parse = (c) => { const m = c.match(/rgba?\\(([^)]+)\\)/); const p = m[1].split(/[ ,\\/]+/).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const over = (f, b) => [f[0] * f[3] + b[0] * (1 - f[3]), f[1] * f[3] + b[1] * (1 - f[3]), f[2] * f[3] + b[2] * (1 - f[3]), 1];
  const L = (c) => { const f = (v) => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(c[0]) + .7152 * f(c[1]) + .0722 * f(c[2]); };
  const el = document.querySelector(${JSON.stringify(sel)});
  const layers = []; for (let n = el; n; n = n.parentElement) { const c = parse(getComputedStyle(n).backgroundColor); if (c[3] > 0) layers.push(c); if (c[3] >= 1) break; }
  let bg = [255, 255, 255, 1]; for (let i = layers.length - 1; i >= 0; i--) bg = over(layers[i], bg);
  let op = 1; for (let n = el; n; n = n.parentElement) op *= +getComputedStyle(n).opacity;
  const f = parse(getComputedStyle(el).color); f[3] *= op; const t = over(f, bg);
  const a = L(t), b = L(bg); return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
})()`;

test("light theme: text and icons that were dark-only on a light surface now read", async () => {
  browser ||= await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  await page.setContent(`<!doctype html><html><head><style>${inline}</style><style>${linked}</style></head><body class="theme-light">${BODY}</body></html>`);
  await page.waitForTimeout(500); // menus fade in
  const need = { "#fh2": 4.5, "#ftag": 4.5, "#frecent": 4.5, "#fhint": 4.5, "#fr3": 4.5, "#fout": 4.5, "#fok": 4.5, "#fwarn": 4.5, "#pmc": 4.5, "#mpl": 4.5, "#scb": 4.5, "#cpl": 4.5 };
  const got = {}, bad = [];
  for (const [s, min] of Object.entries(need)) { got[s] = Math.round(await page.evaluate(RATIO(s)) * 100) / 100; if (got[s] < min) bad.push(`${s} ${got[s]} < ${min}`); }
  assert.deepEqual(bad, [], JSON.stringify(got));
});

test("no inline white text is left in the page (it is invisible on the light surface)", () => {
  const left = [...html.matchAll(/style="[^"]*color:\s*#fff(?:fff)?\b[^"]*"/gi)].map((m) => m[0].slice(0, 80));
  assert.deepEqual(left, []);
});
