/**
 * On a phone the floating report button rests in the strip beside the project tab, level with
 * it, so it is never on message text or on the x of a waiting-message chip. phone.js keeps
 * --phone-fab-b at (window height - message box top + 8); the same value is set here.
 *   node --test tests/bug_fab_phone.test.mjs
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
// The button's own style is injected by the page script, so take its position rules from there.
const fabCss = /#bugReportBtn\{\s*position:fixed;z-index:99998;width:44px;height:44px[^}]*\}/.exec(html)[0];

let browser;
after(async () => { await browser?.close(); });

for (const [w, h] of [[390, 844], [320, 568]]) {
  test(`phone ${w}px: the report button is off the chip x and off the chat`, async () => {
    browser ||= await chromium.launch();
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, hasTouch: true, isMobile: true });
    const page = await ctx.newPage();
    const top = h - 150; // the message box top
    await page.setContent(`<!doctype html><html><head><meta name="viewport" content="width=device-width"><style>${inline}</style><style>${linked}</style><style>${fabCss}
      html{--phone-fab-b:${h - top + 8}px}</style></head><body class="theme-dark">
      <div id="chat" style="position:fixed;left:0;right:0;top:0;height:${top - 48}px"></div>
      <div class="msg-queue-hint" id="msgQueueHint" style="position:fixed;left:0;right:0;top:${top - 48}px"><span class="queue-chip"><span class="queue-chip-text">Will send when the reply finishes: hi</span><button type="button" data-qi="0">×</button></span></div>
      <div class="composer" style="position:fixed;left:0;right:0;top:${top}px;height:150px"></div>
      <button id="bugReportBtn" type="button">🐞</button></body></html>`);
    const r = await page.evaluate(() => {
      const f = document.getElementById("bugReportBtn").getBoundingClientRect();
      const x = document.querySelector("#msgQueueHint button").getBoundingClientRect();
      const hit = document.elementFromPoint(x.left + x.width / 2, x.top + x.height / 2);
      const comp = document.querySelector(".composer").getBoundingClientRect();
      return { fabTop: f.top, fabBottom: f.bottom, compTop: comp.top, hit: hit.id || hit.tagName };
    });
    assert.equal(r.hit, "BUTTON", "the chip x must be what a tap on it reaches");
    assert.ok(r.fabTop >= r.compTop - 1, `the button must not sit above the message box (top ${r.fabTop}, box ${r.compTop})`);
    assert.ok(r.fabBottom <= r.compTop + 46, "and stays in the strip beside the project tab");
    await ctx.close();
  });
}
