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
<div class="chat-titlebar-actions"><button class="chat-share-btn" id="chatExportBtn">Export</button><button class="chat-share-btn" id="chatShareBtn">Share</button></div>
<div class="msg"><div class="meta"><button class="msg-copy">Copy</button><button class="msg-reply">Reply</button><button class="msg-lens">Prompt</button><button class="msg-fork">Fork</button></div><div class="cb-bar"><button class="cb-copy">Copy</button></div></div>
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

for (const [w, h] of [[390, 844], [820, 1180]]) {
  test(`touch ${w}px: every measured control is at least 44x44`, async () => {
    const r = await sizes({ viewport: { width: w, height: h }, hasTouch: true, isMobile: true });
    const small = Object.entries(r).filter(([s, [bw, bh]]) => bw > 0 && (bw < 44 || bh < 44)); // the menu button is hidden on wide screens
    assert.deepEqual(small, []);
  });
}

test("a mouse on a desktop keeps the compact sizes", async () => {
  const r = await sizes({ viewport: { width: 1280, height: 900 } });
  assert.ok(r["#settingsBtn"][0] < 44 && r["#aiSwitchBtn"][1] < 44 && r[".msg-copy"][1] < 44, JSON.stringify(r));
});
