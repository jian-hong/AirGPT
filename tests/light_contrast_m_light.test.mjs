/**
 * Light theme leftovers (m-light.0): project-pick modal, 'Needs setup' chip, Vertex hint lines.
 * Real page CSS in Chromium, transparency composited. Dark and glass computed styles must not change.
 *   node --test tests/light_contrast_m_light.test.mjs
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

const BODY = `<div class="project-pick-modal open" id="m"><div class="project-pick-box" id="box"><h3 id="h3">Choose a project</h3>
<p class="pick-sub" id="sub">Descriptions mix presets.</p><div class="project-pick-grid">
<button class="project-pick-card on" id="cardOn"><h4 id="h4">Chat</h4><p id="p">Base text</p><div class="pick-meta" id="meta">Fresh project</div></button>
<button class="project-pick-card" id="card2"><h4>Code</h4><p>Base</p><div class="pick-meta">Memory</div></button></div>
<button class="btn" id="close">Close</button></div></div>
<div class="mp-card" id="mc"><div><div class="mp-meta"><span class="mp-chip bad" id="chip">Needs setup</span></div></div></div>
<div class="cortex-card" id="cc"><div class="hint" id="v1">Connect a service</div><p class="hint" id="v2" style="margin-top:10px;opacity:.7">Roadmap: publish</p></div>`;

const RATIO = (sel) => `(() => {
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

async function load(cls) {
  browser ||= await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  await page.setContent(`<!doctype html><html><head><style>${inline}</style><style>${linked}</style></head><body class="${cls}">${BODY}</body></html>`);
  await page.waitForTimeout(600);
  return page;
}
const SELS = ["#h3", "#sub", "#h4", "#p", "#meta", "#close", "#chip", "#v1", "#v2"];

test("light theme: project-pick modal, Needs setup chip and Vertex hints read at 4.5:1", async () => {
  const page = await load("theme-light");
  const got = {}, bad = [];
  for (const s of SELS) { got[s] = Math.round(await page.evaluate(RATIO(s)) * 100) / 100; if (got[s] < 4.5) bad.push(`${s} ${got[s]}`); }
  assert.deepEqual(bad, [], JSON.stringify(got));
});

test("dark theme: the same places keep exactly the colours they had at the base commit", async () => {
  const page = await load("");
  const cs = await page.evaluate((sels) => Object.fromEntries(sels.concat(["#box", "#cardOn", "#card2"]).map((s) => { const c = getComputedStyle(document.querySelector(s)); return [s, [c.color, c.backgroundColor, c.borderColor, c.opacity].join("|")]; })), SELS);
  const want = JSON.parse(fs.readFileSync(new URL("fixtures/m_light_dark_styles.json", import.meta.url), "utf8"));
  assert.deepEqual(cs, want);
});
