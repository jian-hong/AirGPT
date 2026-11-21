/**
 * Phone layout lane: chat title bar, bug-report button position, reply rail.
 * The page's own <style>, the /ui/*.css files it links and /ui/phone.js are loaded into Chromium
 * with a stand-in page holding the controls the review measured.
 *   node --test tests/phone_layout.test.mjs
 */
import { test, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright");
const root = new URL("../", import.meta.url);
const html = fs.readFileSync(new URL("index.html", root), "utf8");
const head = html.slice(0, html.indexOf("</head>"));
const inline = [...head.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]).join("\n");
const linked = [...head.matchAll(/<link rel="stylesheet" href="\/(ui\/[^"]+\.css)"/g)].map((m) => fs.readFileSync(new URL(m[1], root), "utf8")).join("\n");
const phoneJs = fs.readFileSync(new URL("ui/phone.js", root), "utf8");
// The real title bar markup, cut from index.html so the test follows the page.
const bar = html.slice(html.indexOf('<div class="chat-titlebar" id="chatTitleBar"'), html.indexOf('<div class="drop-overlay"'));
// Export is added by ui/chattools.js: stand in for it with the same id and classes.
const BODY = `<header class="topbar"><button class="menu-btn">☰</button><div class="topbar-actions"><button class="qr-btn" id="settingsBtn">⚙</button></div></header>
<div class="main-chat-col">${bar.replace('<button type="button" class="chat-share-btn" id="chatShareBtn"', '<button type="button" class="chat-share-btn ctools-export" id="chatExportBtn">Export</button><button type="button" class="chat-share-btn" id="chatShareBtn"')}
<div class="chat" id="chat"></div></div>
<div class="composer" id="composer" style="display:none"></div>
<button id="bugReportBtn" title="drag">B</button>
<textarea id="input"></textarea>`;

let browser;
async function open(opts, { title = "We are planning the Penang office launch", composer = false } = {}) {
  browser ||= await chromium.launch();
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
  await page.setContent(`<!doctype html><html><head><meta name="viewport" content="width=device-width"><style>${inline}</style><style>${linked}</style>
<style>#bugReportBtn{position:fixed;z-index:99998;width:44px;height:44px;padding:0;margin:0;display:grid;place-items:center}</style></head>
<body class="theme-dark">${BODY}</body></html>`);
  await page.evaluate((t) => {
    const b = document.getElementById("chatTitleBar"); b.hidden = false; b.classList.add("show");
    document.getElementById("chatTitleText").textContent = t;
  }, title);
  if (composer) await page.evaluate(() => { document.getElementById("composer").style.display = "block"; });
  await page.addScriptTag({ content: phoneJs });
  await page.waitForTimeout(100);
  return { ctx, page };
}
const PHONE = (w, h = 844) => ({ viewport: { width: w, height: h }, hasTouch: true, isMobile: true });
after(async () => { await browser?.close(); });

for (const w of [320, 390]) {
  test(`phone ${w}px: the chat title gets the row (at least 200px, 16px text)`, async () => {
    const { ctx, page } = await open(PHONE(w));
    const r = await page.evaluate(() => { const t = document.getElementById("chatTitleText"); return { w: t.getBoundingClientRect().width, fs: getComputedStyle(t).fontSize }; });
    await ctx.close();
    assert.ok(r.w >= 200, "title width " + r.w);
    assert.equal(r.fs, "16px");
  });
}

test("phone: a long title stays on one line and ends in an ellipsis", async () => {
  const { ctx, page } = await open(PHONE(320), { title: "A very long chat title that cannot possibly fit on one line of a small phone screen" });
  const r = await page.evaluate(() => { const t = document.getElementById("chatTitleText"), s = getComputedStyle(t); return { h: t.getBoundingClientRect().height, o: s.textOverflow, ws: s.whiteSpace, sw: document.documentElement.scrollWidth }; });
  await ctx.close();
  assert.ok(r.h < 30 && r.o === "ellipsis" && r.ws === "nowrap" && r.sw === 320, JSON.stringify(r));
});

test("phone: the ... menu opens with the three actions, Escape and an outside tap close it, focus returns", async () => {
  const { ctx, page } = await open(PHONE(390));
  const st = () => page.evaluate(() => ({
    ex: document.getElementById("chatMoreBtn")?.getAttribute("aria-expanded"),
    focus: document.activeElement.id,
    items: [...document.querySelectorAll("#chatTitleActions button")].filter((b) => b.offsetParent).map((b) => (b.querySelector(".cta-lab") || b).textContent.trim()),
  }));
  const more = await page.evaluate(() => { const b = document.getElementById("chatMoreBtn"); return b && { hp: b.getAttribute("aria-haspopup"), disp: getComputedStyle(b).display, w: b.getBoundingClientRect().width }; });
  assert.ok(more && more.hp === "menu" && more.disp !== "none" && more.w <= 36, JSON.stringify(more));
  assert.deepEqual((await st()).items, []);
  await page.tap("#chatMoreBtn");
  let s = await st();
  assert.equal(s.ex, "true");
  assert.deepEqual(s.items.map((x) => x.replace(/\s+/g, " ")), ["Background tasks", "Export", "Share"]);
  assert.equal(await page.evaluate(() => document.getElementById("chatTitleActions").getAttribute("role")), "menu");
  await page.keyboard.press("Escape");
  s = await st();
  assert.equal(s.ex, "false"); assert.equal(s.focus, "chatMoreBtn"); assert.deepEqual(s.items, []);
  await page.tap("#chatMoreBtn");
  await page.mouse.click(40, 600);
  assert.equal((await st()).ex, "false");
  await ctx.close();
});

test("phone: choosing an action runs it and closes the menu", async () => {
  const { ctx, page } = await open(PHONE(390));
  await page.evaluate(() => { window.__hit = []; window.bgTasks = { open() { window.__hit.push("bg"); } }; window.shareChatFromHeader = () => window.__hit.push("share"); });
  await page.tap("#chatMoreBtn"); await page.tap("#bgTasksTitleBtn");
  await page.tap("#chatMoreBtn"); await page.tap("#chatShareBtn");
  const r = await page.evaluate(() => ({ hit: window.__hit, ex: document.getElementById("chatMoreBtn").getAttribute("aria-expanded") }));
  const focus = await page.evaluate(() => document.activeElement.id); // not lost when the menu closes after an action
  await ctx.close();
  assert.equal(focus, "chatMoreBtn");
  assert.deepEqual(r, { hit: ["bg", "share"], ex: "false" });
});

test("laptop with a mouse: title bar is exactly as before (no ... button, three buttons in the row, 14px title)", async () => {
  for (const [w, h] of [[1280, 800], [1920, 1080]]) {
    const { ctx, page } = await open({ viewport: { width: w, height: h } });
    const r = await page.evaluate(() => {
      const d = (id) => getComputedStyle(document.getElementById(id)).display;
      const t = document.getElementById("chatTitleText");
      return { more: d("chatMoreBtn"), acts: d("chatTitleActions"), lay: document.getElementById("bgTasksTitleBtn").getBoundingClientRect().width, lab: getComputedStyle(document.querySelector(".cta-lab")).display, fs: getComputedStyle(t).fontSize, pos: getComputedStyle(document.getElementById("chatTitleBar")).position, role: document.getElementById("chatShareBtn").getAttribute("role") };
    });
    await ctx.close();
    assert.deepEqual(r, { more: "none", acts: "flex", lay: r.lay, lab: "none", fs: "14px", pos: "static", role: null });
    assert.ok(r.lay > 0);
  }
});

for (const w of [320, 390]) {
  test(`phone ${w}px: with the message box hidden the bug button stays off the top bar and the gear is tappable`, async () => {
    const { ctx, page } = await open(PHONE(w, w === 320 ? 568 : 844));
    const r = await page.evaluate(() => {
      const g = document.getElementById("settingsBtn").getBoundingClientRect(), b = document.getElementById("bugReportBtn").getBoundingClientRect();
      const hit = document.elementFromPoint(g.x + g.width / 2, g.y + g.height / 2);
      return { hit: hit && hit.id, bugTop: b.top, bugBottom: b.bottom, bar: document.querySelector(".topbar").getBoundingClientRect().bottom, ih: innerHeight };
    });
    await ctx.close();
    assert.equal(r.hit, "settingsBtn", JSON.stringify(r));
    assert.ok(r.bugTop >= r.bar && r.bugBottom <= r.ih, JSON.stringify(r));
  });
}

test("phone: with a message box the bug button still rests just above it", async () => {
  const { ctx, page } = await open(PHONE(390), { composer: true });
  await page.evaluate(() => { const c = document.getElementById("composer"); c.style.cssText = "display:block;position:fixed;left:0;right:0;bottom:0;height:150px"; });
  await page.evaluate(() => window.dispatchEvent(new Event("resize")));
  await page.waitForTimeout(100);
  const r = await page.evaluate(() => ({ b: document.getElementById("bugReportBtn").getBoundingClientRect().bottom, c: document.getElementById("composer").getBoundingClientRect().top }));
  await ctx.close();
  assert.ok(Math.abs(r.b - r.c) < 80, JSON.stringify(r)); // level with the project tab, not far above or below the box
});

/* The reply rail: only in a chat. */
function grab(name) {
  const m = new RegExp("^function " + name + "\\(", "m").exec(html);
  let i = html.indexOf("{", m.index), depth = 0;
  for (let j = i; j < html.length; j++) { if (html[j] === "{") depth++; else if (html[j] === "}" && --depth === 0) return html.slice(m.index, j + 1); }
}
test("reply rail: hidden in OpenIDE and when the page has no replies, shown in a chat", () => {
  const mk = (n, cls) => {
    const track = { dataset: { sig: "x" }, querySelectorAll: () => [], appendChild() {} };
    const bar = { hidden: true, dataset: {} };
    const nodes = Array.from({ length: n }, (_, i) => ({ id: "msg-" + i }));
    const ctx = vm.createContext({
      $: (id) => ({ msgJumpBar: bar, msgJumpTrack: track, msgJumpCount: { textContent: "" } })[id],
      aiMsgNodes: () => nodes, paintJumpNodes() {}, document: { body: { classList: { contains: (c) => c === cls }, } , createElement: () => ({ dataset: {}, setAttribute() {} }) },
    });
    vm.runInContext(grab("updateMsgJumpBar") + "\nupdateMsgJumpBar()", ctx);
    return bar.hidden;
  };
  assert.equal(mk(2, ""), false);
  assert.equal(mk(2, "openide-mode"), true);
  assert.equal(mk(0, ""), true);
});
test("reply rail: re-checked when a page replaces #chat or the page mode changes", () => {
  assert.match(html, /new MutationObserver\(q\)\.observe\(c,\{childList:true\}\)/);
  assert.match(html, /new MutationObserver\(q\)\.observe\(document\.body,\{attributes:true,attributeFilter:\['class'\]\}\)/);
});

test("phone: the open ... menu sits above the reply rail (z-index 22)", async () => {
  const { ctx, page } = await open(PHONE(320, 568));
  await page.tap("#chatMoreBtn");
  const z = await page.evaluate(() => +getComputedStyle(document.getElementById("chatTitleBar")).zIndex);
  await ctx.close();
  assert.ok(z > 22, "title bar z-index " + z);
});
