/**
 * Round 3 visual lane: bugs found by measuring every screen at phone, tablet and desktop sizes.
 * The page's own <style> and the /ui/*.css files it links (in order) are loaded into Chromium with a
 * stand-in page; the real OpenIDE sheet is added for the OpenIDE checks.
 *   node --test tests/visual_r3.test.mjs
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
const linked = [...head.matchAll(/<link rel="stylesheet" href="\/((?:ui|OpenIDE\/ui)\/[^"]+\.css)"/g)].map((m) => fs.readFileSync(new URL(m[1], root), "utf8")).join("\n");

let browser;
after(async () => { await browser?.close(); });
async function page(body, opts, theme = "dark") {
  browser ||= await chromium.launch();
  const ctx = await browser.newContext(opts);
  const p = await ctx.newPage();
  await p.setContent(`<!doctype html><html><head><meta name="viewport" content="width=device-width"><style>${inline}</style><style>${linked}</style></head><body class="theme-${theme}">${body}</body></html>`);
  return [p, ctx];
}
const PHONE = { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true };
const TABLET = { viewport: { width: 820, height: 1180 }, hasTouch: true, isMobile: true };

test("the + button is round like the mic button on a phone (light theme showed a grey rounded square)", async () => {
  const [p, ctx] = await page(`<div class="composer"><div class="composer-row"><div class="plus-menu-wrap"><button type="button" id="attachBtn" class="attach-plus">+</button></div><button class="mic-btn" id="micBtn">M</button></div></div>`, PHONE, "light");
  const r = await p.evaluate(() => ({ plus: getComputedStyle(attachBtn).borderRadius, mic: getComputedStyle(micBtn).borderRadius }));
  assert.equal(r.plus, "50%", JSON.stringify(r));
  await ctx.close();
});

test("the reply rail is hidden on a phone, one reply or many (round 3b: it still sat over code and text at 320px with two or more)", async () => {
  const [p, ctx] = await page(`<div class="msg-jump-bar" id="one" data-n="one"><div class="msg-jump-track"></div></div><div class="msg-jump-bar" id="many" data-n="many"><div class="msg-jump-track"></div></div>`, PHONE);
  const r = await p.evaluate(() => [getComputedStyle(one).display, getComputedStyle(many).display]);
  assert.deepEqual(r, ["none", "none"]);
  assert.match(html, /bar\.dataset\.n=n>1\?'many':'one'/, "the page must set data-n on the rail");
  await ctx.close();
});

test("Copy, Reply, Prompt, Fork and Regenerate are the same height on a phone (Fork and Regenerate were 28px, the rest 20px)", async () => {
  const [p, ctx] = await page(`<div class="msg ai-msg turn-last-ai"><div class="bub"><div class="meta"><button class="msg-copy">Copy</button><button class="msg-reply">Reply</button><button class="msg-lens">Prompt</button><button class="msg-fork">Fork</button><button class="msg-regen">Regenerate</button></div></div></div>`, PHONE);
  const h = await p.evaluate(() => [...document.querySelectorAll(".meta button")].map((b) => Math.round(b.getBoundingClientRect().height)));
  assert.equal(new Set(h).size, 1, "heights " + h);
  await ctx.close();
});

test("the + sheet labels start at the same x whatever the icon is (emoji and glyph icons differ in width)", async () => {
  const items = ["📎", "⌘", "🌐", "🔎", "▦", "✦", "☰"].map((i) => `<button type="button" role="menuitem"><span class="pm-ico">${i}</span><span class="lab">Label</span></button>`).join("");
  const [p, ctx] = await page(`<div class="composer"><div class="plus-menu open" id="pm">${items}</div></div>`, PHONE);
  const xs = await p.evaluate(() => [...document.querySelectorAll("#pm .lab")].map((e) => Math.round(e.getBoundingClientRect().left * 10) / 10));
  assert.equal(new Set(xs).size, 1, "label x " + xs);
  await ctx.close();
});

test("drawer group labels and the relative time keep 4.5:1 text contrast", async () => {
  const [p, ctx] = await page(`<aside class="side" style="background:#101010"><div class="side-nav"><button class="nav-label" id="nl">Build</button></div><div class="session-item dense on" style="background:#2a2a2a"><span class="sess-rel" id="rel">now</span></div></aside>`, PHONE);
  const r = await p.evaluate(() => {
    const L = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
    const rgb = (s) => s.match(/[\d.]+/g).map(Number);
    const ratio = (el, bg) => { const cs = getComputedStyle(el); const fg = rgb(cs.color), o = +cs.opacity; const comp = fg.slice(0, 3).map((v, i) => v * o + bg[i] * (1 - o)); const a = L(comp), b = L(bg); return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05); };
    return { nl: ratio(nl, [16, 16, 16]), rel: ratio(rel, [42, 42, 42]) };
  });
  assert.ok(r.nl >= 4.5, "nav label " + r.nl);
  assert.ok(r.rel >= 4.5, "relative time " + r.rel);
  await ctx.close();
});

test("OpenIDE on a phone: hero sits at the top of its box and the IDE button stays on one line", async () => {
  const [p, ctx] = await page(`<div class="topbar"><button class="qr-btn" id="openideIdeBtn">IDE ↗</button></div><div class="openide-empty-hint" id="h"><h3>Create an app</h3></div>`, PHONE);
  const r = await p.evaluate(() => ({ mt: getComputedStyle(h).marginTop, ws: getComputedStyle(openideIdeBtn).whiteSpace, lines: Math.round(openideIdeBtn.getBoundingClientRect().height) }));
  assert.equal(r.mt, "0px");
  assert.equal(r.ws, "nowrap");
  assert.ok(r.lines <= 44, JSON.stringify(r));
  await ctx.close();
});

// Tap area: the 44x44 box centred on the control must mostly belong to it (a layer counts, a neighbour's layer does not).
async function owned(p, sel) {
  return p.evaluate((s) => {
    const el = document.querySelector(s); const r = el.getBoundingClientRect(); const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    let xs = [], ys = [];
    for (let dx = -22; dx <= 22; dx += 2) for (let dy = -22; dy <= 22; dy += 2) { const h = document.elementFromPoint(cx + dx, cy + dy); if (h && (h === el || el.contains(h))) { xs.push(dx); ys.push(dy); } }
    return [Math.max(Math.max(...xs) - Math.min(...xs) + 2, r.width), Math.max(Math.max(...ys) - Math.min(...ys) + 2, r.height)];
  }, sel);
}

test("touch: Marketplace buttons, Cortex buttons and Details folds reach 44px", async () => {
  const [p, ctx] = await page(`<div style="padding:30px"><div class="mp-actions"><button class="btn" id="a">Install</button></div><div class="cortex-card"><button class="btn" id="b">Prep llama.cpp</button></div><details><summary id="c">Details</summary><p>x</p></details></div>`, PHONE);
  for (const s of ["#a", "#b", "#c"]) { const [w, h] = await owned(p, s); assert.ok(h >= 44, `${s} ${w}x${h}`); }
  await ctx.close();
});

test("touch: OpenIDE chips, tabs and glass buttons reach 44px (layers do not change the layout)", async () => {
  const [p, ctx] = await page(`<div class="openide-shell" style="padding:30px"><div class="openide-app-chips"><button class="openide-app-chip" id="a">▶ one</button><button class="openide-app-chip" id="a2">▶ two</button></div><div><button class="oide-glass-btn" id="b">Folder</button></div><button id="openideWorkBrowser">Browser</button></div>`, PHONE);
  for (const s of ["#a", "#b", "#openideWorkBrowser"]) { const [w, h] = await owned(p, s); assert.ok(h >= 40 && w >= 40, `${s} ${w}x${h}`); }
  await ctx.close();
});

test("tablet touch: drawer rows and Pin/Archive reach 44px", async () => {
  const [p, ctx] = await page(`<aside class="side" style="position:static;width:300px"><button class="nav-item" id="n">New chat</button><div class="session-item dense on"><div class="sess-actions-inline"><button id="pin">P</button><button id="arc">A</button></div></div></aside>`, TABLET);
  const nav = await p.evaluate(() => Math.round(n.getBoundingClientRect().height));
  assert.ok(nav >= 44, "nav-item " + nav);
  const [, h] = await owned(p, "#pin");
  assert.ok(h >= 40, "pin " + h);
  await ctx.close();
});

test("the preview line on the open drawer row keeps 4.5:1 text contrast", async () => {
  const [p, ctx] = await page(`<aside class="side" style="background:#101010"><div class="session-item dense on" style="background:#2a2a2a"><div class="sess-detail-inner"><div class="sess-preview" id="pv">Launch plan</div></div></div></aside>`, PHONE);
  const r = await p.evaluate(() => {
    const L = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
    const cs = getComputedStyle(pv), fg = cs.color.match(/[\d.]+/g).map(Number), o = +cs.opacity, bg = [42, 42, 42];
    const a = L(fg.slice(0, 3).map((v, i) => v * o + bg[i] * (1 - o))), b = L(bg);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  });
  assert.ok(r >= 4.5, "preview " + r);
  await ctx.close();
});
