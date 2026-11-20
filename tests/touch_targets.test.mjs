/**
 * Touch screens get 44px controls at any width; a mouse keeps the compact sizes.
 * The page's own <style> and the /ui/*.css files it links (in order) are loaded into Chromium
 * with a stand-in page holding the controls the review measured.
 *   node --test tests/touch_targets.test.mjs
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
const BODY = `<div class="topbar"><button class="menu-btn">☰</button><button class="qr-btn bgtasks-top-btn" id="bgTasksTopBtn">0</button><button class="qr-btn" id="settingsBtn">⚙</button>
<button class="ai-switch-track on" id="aiSwitchBtn"><span class="ai-switch-thumb"></span></button></div>
<div class="chat-titlebar-actions" style="position:relative;z-index:100"><button class="chat-share-btn" id="chatExportBtn">Export</button><button class="chat-share-btn" id="chatShareBtn">Share</button></div>
<div class="msg" style="padding:16px 0"><div class="meta"><button class="msg-copy">Copy</button><button class="msg-reply">Reply</button><button class="msg-lens">Prompt</button><button class="msg-fork">Fork</button></div><div class="cb-bar"><button class="cb-copy">Copy</button></div></div>
<div id="settingsModal"><button class="btn" id="restartTunnelBtn">↻</button><button class="ds-ico">✎</button><button class="field-eye">👁</button></div>`;
const SEL = [".menu-btn", "#bgTasksTopBtn", "#settingsBtn", "#aiSwitchBtn", "#chatExportBtn", "#chatShareBtn", ".msg-copy", ".msg-reply", ".msg-lens", ".msg-fork", ".cb-copy", "#restartTunnelBtn", ".ds-ico", ".field-eye"];

let browser;
async function sizes(opts) {
  browser ||= await chromium.launch();
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
  await page.setContent(`<!doctype html><html><head><meta name="viewport" content="width=device-width"><style>${inline}</style><style>${linked}</style></head><body class="theme-dark phone-client">${BODY}</body></html>`);
  const r = await page.evaluate((sel) => Object.fromEntries(sel.map((s) => {
    const b = document.querySelector(s).getBoundingClientRect(); return [s, [b.width, b.height]];
  })), SEL);
  await ctx.close();
  return r;
}
after(async () => { await browser?.close(); });

// Tap area: the 44x44 box centred on a control must hit that control (or a child, or the label around a checkbox).
// Each control is tested on its own (the others are hidden) so the test measures the layer, not the neighbours.
// The listed controls keep a compact look: their visible box is under 44 high; only the tap area is 44.
const BODY2 = `<div style="padding:24px"><div class="topbar-x"><button id="sideToggleTop" class="side-toggle-top">☰</button></div>
<div class="composer"><div class="composer-row"><button id="modelBtn">gpt</button><button id="thinkBtn">T</button><button id="micBtn">M</button><button class="cprefs-btn">Instructions</button><button class="plens-meter">12%</button></div></div>
<div class="msg-queue-hint"><span class="queue-chip"><span class="queue-chip-text">later</span><button id="qx" data-qi="0">×</button></span></div>
<div class="msg-queue-hint edit-chip"><span>Editing</span><button id="editChipCancel">Cancel</button></div>
<div class="lan-banner" style="position:relative;height:50px"><button class="banner-x" id="bx">×</button></div>
<div class="rag-space-head"><button class="rag-back" id="rb">←</button></div><div class="rag-tabs"><button class="btn" id="rt">Ask</button></div><button class="rag-back-sessions" id="rs">All sessions</button>
<div class="hub-share-row"><button class="btn primary" id="tc">Team code</button></div><button class="btn danger-wide" id="hubLockdownBtn">Cut all AI</button>
<div class="send-fail-acts"><button class="btn primary" id="sk">Add an API key</button></div>
<div id="bgTasksPanel"><div class="bgHead" style="display:flex;gap:8px;padding:14px 16px"><button id="bgr">↻</button><button id="bgc">×</button></div><div class="bgFoot"><button id="bgf">Finished</button></div></div>
<div class="plus-menu open" id="pm"><button id="pmb">Files</button></div>
<label class="hub-demo-toggle"><input type="checkbox" id="hdt"> Demo mode</label>
<div id="settingsModal"><label class="settings-check"><input type="checkbox" id="sca"> Auto</label></div></div>`;
const TAP = ["#settingsBtn", "#bgTasksTopBtn", ".menu-btn", "#chatShareBtn", "#chatExportBtn", ".msg-copy", ".msg-reply", ".msg-lens", ".msg-fork", ".cb-copy",
  "#sideToggleTop", "#modelBtn", "#thinkBtn", "#micBtn", ".cprefs-btn", ".plens-meter", "#qx", "#editChipCancel", "#bx", "#rb", "#rt", "#rs", "#tc", "#hubLockdownBtn", "#sk", "#bgr", "#bgc", "#bgf", "#hdt", "#sca"];
const COMPACT = ["#settingsBtn", "#bgTasksTopBtn", ".menu-btn", "#chatShareBtn", "#chatExportBtn", ".msg-copy", ".msg-reply", ".msg-lens", ".msg-fork", ".cb-copy", "#sideToggleTop", "#modelBtn", "#thinkBtn", "#micBtn", ".cprefs-btn", ".plens-meter", "#qx", "#editChipCancel", "#rb", "#rt", "#rs", "#tc", "#bgf"]; // Add an API key is already a 44px button on a phone

async function tapAreas(opts) {
  browser ||= await chromium.launch();
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
  await page.setContent(`<!doctype html><html><head><meta name="viewport" content="width=device-width"><style>${inline}</style><style>${linked}</style></head><body class="theme-dark phone-client" style="padding-top:100px">${BODY}${BODY2}<div style="height:200px"></div></body></html>`);
  const r = await page.evaluate((sels) => {
    const out = {};
    for (const s of sels) {
      const e = document.querySelector(s);
      if (!e || !e.getBoundingClientRect().width) { out[s] = { gone: true }; continue; }
      document.querySelectorAll("button,input").forEach((x) => { if (x !== e) x.style.visibility = "hidden"; });
      e.scrollIntoView({ block: "center" });
      const b = e.getBoundingClientRect(), cx = b.x + b.width / 2, cy = b.y + b.height / 2, lab = e.closest("label");
      const miss = [];
      for (const [dx, dy] of [[-20, -20], [20, -20], [-20, 20], [20, 20]]) {
        const h = document.elementFromPoint(cx + dx, cy + dy);
        if (!(h && (h === e || e.contains(h) || (lab && lab.contains(h))))) miss.push(dx + "," + dy);
      }
      document.querySelectorAll("button,input").forEach((x) => { x.style.visibility = ""; });
      out[s] = { w: Math.round(b.width), h: Math.round(b.height), miss };
    }
    return out;
  }, TAP);
  await ctx.close();
  return r;
}

for (const [w, h] of [[390, 844], [820, 1180]]) {
  test(`touch ${w}px: a 44x44 area around every listed control taps that control`, async () => {
    const r = await tapAreas({ viewport: { width: w, height: h }, hasTouch: true, isMobile: true });
    const bad = Object.entries(r).filter(([s, v]) => !v.gone && v.miss.length);
    assert.deepEqual(bad, []);
  });
  test(`touch ${w}px: the buttons keep a compact look (under 44 high); only the tap area is 44`, async () => {
    const r = await tapAreas({ viewport: { width: w, height: h }, hasTouch: true, isMobile: true });
    const heavy = COMPACT.filter((s) => r[s] && !r[s].gone && r[s].h >= 44);
    assert.deepEqual(heavy, []);
  });
}

test("a mouse on a desktop keeps the compact sizes", async () => {
  const r = await sizes({ viewport: { width: 1280, height: 900 } });
  assert.ok(r["#settingsBtn"][0] < 44 && r["#aiSwitchBtn"][1] < 44 && r[".msg-copy"][1] < 44, JSON.stringify(r));
});
