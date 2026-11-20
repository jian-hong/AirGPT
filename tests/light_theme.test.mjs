/**
 * Light theme contrast and Mermaid colours, measured from computed styles in a real browser
 * (index.html opened from disk, no server). Text must reach 4.5:1 and icons or lines 3:1 once
 * transparent backgrounds and opacity are composited. Run with:
 *   node --test tests/light_theme.test.mjs
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const INDEX = new URL("../index.html", import.meta.url);
const html = fs.readFileSync(INDEX, "utf8");

// Measure `sel` inside the light theme: colour of its own text over the composited
// background (walking up through parents), with every ancestor's opacity applied.
const MEASURE = ([sel, hover]) => {
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const over = (f, b) => [f[0] * f[3] + b[0] * (1 - f[3]), f[1] * f[3] + b[1] * (1 - f[3]), f[2] * f[3] + b[2] * (1 - f[3]), 1];
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const el = document.querySelector(sel);
  if (!el) return { error: "missing " + sel };
  let stack = [], op = 1;
  for (let e = el; e; e = e.parentElement) {
    const cs = getComputedStyle(e); op *= parseFloat(cs.opacity);
    const c = parse(cs.backgroundColor); if (c[3] > 0) stack.push(c); if (c[3] >= 1) break;
  }
  let bg = [255, 255, 255, 1]; for (const c of stack.reverse()) bg = over(c, bg);
  const fg0 = parse(getComputedStyle(el).color);
  const fg = over([fg0[0], fg0[1], fg0[2], fg0[3] * op], bg);
  const a = lum(fg), b = lum(bg);
  return { ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) };
};

let browser, page;
before(async () => {
  browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 850 } });
  await ctx.addInitScript(() => { try { localStorage.setItem("airgpt_theme", "light"); } catch (e) {} });
  page = await ctx.newPage();
  await page.goto(INDEX.href);
  await page.waitForFunction(() => document.body.classList.contains("theme-light"));
  // Rows that are normally drawn from data, built with the same classes.
  await page.evaluate(() => {
    const host = document.createElement("div");
    host.id = "ltHost";
    host.style.cssText = "position:fixed;left:0;top:0;width:900px;background:var(--surface);z-index:99999";
    host.innerHTML = `
      <div class="ds-row"><span class="ds-acts"><button class="ds-ico" id="ltEdit">✎</button><button class="ds-ico danger" id="ltDel">✕</button></span></div>
      <button class="ds-add" id="ltAdd"><span class="ds-plus">+</span></button>
      <div class="side-nav"><div class="nav-item" id="ltNavItem">Hosting<span class="nav-beta" id="ltBeta">Beta</span></div></div>
      <div class="msg-jump-bar" style="position:static"><div class="msg-jump-count" id="ltJump">12</div></div>`;
    document.body.appendChild(host);
  });
});
after(async () => { await browser.close(); });

const ratio = async (sel) => { const r = await page.evaluate(MEASURE, [sel]); assert.ok(!r.error, r.error); return r.ratio; };

test("API key eye uses the text colour, not white", async () => {
  await page.evaluate(() => openSettings("models"));
  assert.ok((await ratio("#scPanel-models .field-eye")) >= 4.5);
});

test("inactive Settings nav items reach 4.5:1", async () => {
  await page.evaluate(() => openSettings("general"));
  for (const sel of ["#scNavList .sc-nav-item:not(.on)", "#settingsModal .sc-docs"]) assert.ok((await ratio(sel)) >= 4.5, sel);
});

test("sidebar Beta badge, section labels and RAG back link reach 4.5:1", async () => {
  await page.evaluate(() => { closeSettings(); document.querySelector(".app").classList.remove("side-collapsed"); });
  await page.addStyleTag({ content: "*{transition:none!important}" });
  for (const sel of ["#ltBeta", ".side-nav .nav-label", ".side-section-hdr", "#ltJump"]) {
    const r = await page.evaluate(MEASURE, [sel]);
    if (r.error) continue;   // not on this screen
    assert.ok(r.ratio >= 4.5, sel + " " + r.ratio);
  }
  await page.evaluate(() => { const b = document.createElement("button"); b.className = "rag-back-sessions"; b.id = "ltBack"; b.textContent = "All sessions"; document.getElementById("ltHost").appendChild(b); });
  assert.ok((await ratio("#ltBack")) >= 4.5);
});

test("Rules and Skills icons and the + reach 3:1", async () => {
  for (const sel of ["#ltEdit", "#ltDel", "#ltAdd .ds-plus"]) assert.ok((await ratio(sel)) >= 4.5, sel);
});

test("failed colours (run card tag, task failure) reach 4.5:1 in light", async () => {
  await page.evaluate(() => {
    const h = document.getElementById("ltHost");
    h.insertAdjacentHTML("beforeend", `<div class="cortex-call">${cortexCallDetailHtml([{ name: "web_search", ok: false, result: { ok: false } }])}</div>
      <div id="bgTasksPanel" style="position:static;display:block"><div class="bgBody"><div class="bgCard"><div class="bgDesc" id="ltBgErr" style="color:#e03131">Engine offline</div><div class="bgLabel">Phases <span id="ltBgCount" style="opacity:.6">1/1</span></div><div class="bgPhaseHd"><span class="cv" id="ltBgChev">&#9654;</span></div><div class="bgHead"><button id="ltBgRefresh">&#8635;</button></div></div></div></div>`);
  });
  // The panel's own CSS is added by its script; skip the BG rows if it has not run.
  const tag = await page.evaluate(MEASURE, [".cortex-call span"]);
  assert.ok(tag.ratio >= 4.5, "failed tag " + tag.ratio);
  for (const sel of ["#ltBgErr", "#ltBgCount", "#ltBgChev", "#ltBgRefresh"]) assert.ok((await ratio(sel)) >= 3, sel);
});

test("Mermaid palette follows the always-dark diagram panel", async () => {
  const cfg = await page.evaluate(() => {
    let got = null;
    const real = window.mermaid;
    window.mermaid = { initialize: (c) => { got = c; } };
    _mermaidReady = false;
    initMermaid();
    window.mermaid = real;
    return got;
  });
  assert.ok(cfg, "mermaid.initialize was not called");
  const panel = [13, 17, 23];
  const m = cfg.themeVariables.lineColor.match(/rgba?\(([^)]+)\)/);
  const [r, g, b, a = 1] = m[1].split(",").map(Number);
  const mix = [r, g, b].map((v, i) => v * a + panel[i] * (1 - a));
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratioLine = (lum(mix) + 0.05) / (lum(panel) + 0.05);
  assert.ok(ratioLine >= 3, "line colour on the diagram panel is " + ratioLine.toFixed(2));
});

test("sweep misses: RAG stage link, danger button, add tile, error hints, key manager counts", async () => {
  await page.evaluate(() => {
    document.getElementById("ltHost").insertAdjacentHTML("beforeend", `
      <div class="rag-chat-stage" style="height:auto;min-height:0;animation:none"><button class="rag-back-sessions" id="ltStageBack">All sessions</button><p class="hint" id="ltStageHint">No messages yet</p></div>
      <button class="btn danger" id="ltDanger">Delete</button>
      <p class="hint" id="ltErrHint" style="color:#e03131">Could not reach the engine.</p>
      <p class="cortex-tag"><strong id="ltTagStrong">cpu_gguf</strong></p>
      <div id="keyVaultModal"><button class="kv-group-btn" id="ltKvBtn">Cloud <span id="ltKvCount" style="opacity:.7">0/7</span></button></div>`);
  });
  for (const sel of ["#ltStageBack", "#ltStageHint", "#ltDanger", "#ltErrHint", "#ltTagStrong", "#ltKvCount"]) {
    const r = await page.evaluate(MEASURE, [sel]);
    assert.ok(r.ratio >= 4.5, sel + " " + r.ratio);
  }
});

test("saving a new key forgets an earlier refusal", () => {
  const i = html.indexOf("async function saveSettings(");
  const body = html.slice(i, i + 1500);
  assert.ok(body.includes("localStorage.removeItem('airgpt_key_refused')"));
});
