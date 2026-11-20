/**
 * Chat title bar ... menu on a phone: a see-through theme must not let reply text show
 * through the open menu, and the Export formats must open in place so Share stays
 * visible and tappable.  node --test tests/chat_menu_ui.test.mjs
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
const phoneJs = fs.readFileSync(new URL("ui/phone.js", root), "utf8");
const toolsJs = fs.readFileSync(new URL("ui/chattools.js", root), "utf8");
const bar = html.slice(html.indexOf('<div class="chat-titlebar" id="chatTitleBar"'), html.indexOf('<div class="drop-overlay"'));
let browser;
after(async () => { await browser?.close(); });

async function open(theme, w) {
  browser ||= await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: w, height: 844 }, hasTouch: true, isMobile: true });
  const page = await ctx.newPage();
  const cls = theme === "glass" ? "" : "theme-" + theme;
  await page.setContent(`<!doctype html><html><head><meta name="viewport" content="width=device-width"><style>${inline}</style><style>${linked}</style></head>
<body class="${cls}"><div class="main-chat-col" style="min-height:100vh">${bar}<div class="chat" id="chat"><p id="reply" style="margin:0;padding:40px 12px;font-size:16px;color:#fff">Reply text behind the menu</p></div></div><div class="composer" style="display:none"></div><textarea id="input" style="display:none"></textarea></body></html>`);
  await page.evaluate(() => { const b = document.getElementById("chatTitleBar"); b.hidden = false; b.classList.add("show"); });
  await page.addScriptTag({ content: toolsJs });
  await page.addScriptTag({ content: phoneJs });
  await page.waitForTimeout(100);
  await page.click("#chatMoreBtn");
  return { ctx, page };
}

for (const w of [320, 390]) {
  test(`glass ${w}px: the open ... menu is opaque`, async () => {
    const { ctx, page } = await open("glass", w);
    const bg = await page.evaluate(() => getComputedStyle(document.getElementById("chatTitleActions")).backgroundColor);
    await ctx.close();
    const a = /rgba\(.*,\s*([\d.]+)\)$/.exec(bg);
    assert.ok(!a || Number(a[1]) === 1, "menu background " + bg);
  });

  test(`${w}px: the Export formats open in place and Share stays uncovered`, async () => {
    for (const theme of ["glass", "light", "dark"]) {
      const { ctx, page } = await open(theme, w);
      await page.click("#chatExportBtn");
      const r = await page.evaluate(() => {
        const R = (e) => e.getBoundingClientRect();
        const sh = R(document.getElementById("chatShareBtn")), items = [...document.querySelectorAll(".ctools-menu button")].map(R);
        const hit = document.elementFromPoint(sh.left + sh.width / 2, sh.top + sh.height / 2);
        return { vh: innerHeight, share: sh.toJSON(), items: items.map((i) => i.toJSON()), stack: document.elementsFromPoint(sh.left + sh.width / 2, sh.top + sh.height / 2).map((e) => e.id || e.className || e.tagName).join(">"), hit: hit && hit.closest("#chatShareBtn") ? "share" : hit && (hit.className || hit.tagName) };
      });
      await ctx.close();
      assert.equal(r.items.length, 2, theme);
      assert.equal(r.hit, "share", `${theme} ${w}: Share centre is covered by ${r.hit} ${JSON.stringify(r)}`);
      for (const i of r.items) {
        assert.ok(i.bottom <= r.share.top + 0.5 || i.top >= r.share.bottom - 0.5, `${theme} ${w}: format overlaps Share`);
        assert.ok(i.height >= 44, `${theme} ${w}: format row is ${i.height}px tall`);
      }
    }
  });
}
