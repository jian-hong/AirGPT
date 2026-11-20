/**
 * Small UI findings, round 2: the chat title keeps its full text (CSS cuts it), a disabled
 * button looks disabled and OpenFree stops promising a one-tap start it cannot do, placeholders
 * read in the light theme.   node --test tests/round2_ui_bits.test.mjs
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
let browser;
after(async () => { await browser?.close(); });
function grab(name) {
  const m = new RegExp("^(async )?function " + name + "\\(", "m").exec(html);
  assert.ok(m, name + " missing");
  let depth = 0;
  for (let j = html.indexOf("{", m.index); j < html.length; j++) {
    if (html[j] === "{") depth++;
    else if (html[j] === "}" && --depth === 0) return html.slice(m.index, j + 1);
  }
  throw new Error("unbalanced");
}

test("the chat title bar gets the whole title; the sidebar keeps the short one", () => {
  const ctx = vm.createContext({ mdPlain: (s) => String(s), sessionShortDate: () => "" });
  vm.runInContext(grab("summarizeChatTitle") + grab("sessionCompactTitle"), ctx);
  const s = { title: "Plan the Penang office launch for next quarter with the full budget" };
  assert.ok(ctx.sessionCompactTitle(s).length <= 36 && ctx.sessionCompactTitle(s).endsWith("…"));
  assert.equal(ctx.sessionCompactTitle(s, true), s.title);
  assert.match(html, /titleEl\.textContent=sessionTitleForId\(sid,true\)/);
});

test("a disabled button looks disabled, and OpenFree does not promise a tap it cannot do", async () => {
  browser ||= await chromium.launch();
  const page = await (await browser.newContext()).newPage();
  await page.setContent(`<!doctype html><html><head><style>${inline}</style><style>${linked}</style></head><body><button class="btn primary" id="d" disabled>Enable</button></body></html>`);
  const r = await page.evaluate(() => { const c = getComputedStyle(document.getElementById("d")); return { o: c.opacity, cur: c.cursor }; });
  assert.ok(Number(r.o) < 0.7 && r.cur === "not-allowed", JSON.stringify(r));
  assert.match(html, /isOpenFree&&cantFree\?'':`<p class="hint kv-note">/);
});

test("light theme: placeholders are readable", async () => {
  browser ||= await chromium.launch();
  const page = await (await browser.newContext()).newPage();
  await page.setContent(`<!doctype html><html><head><style>${inline}</style><style>${linked}</style></head><body class="theme-light"><input id="i" placeholder="Paste key" style="background:#f0eee8"><textarea id="t" placeholder="Message" style="background:#f0eee8"></textarea></body></html>`);
  const lum = (c) => { const v = c.match(/[\d.]+/g).slice(0, 3).map((x) => { x /= 255; return x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4; }); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
  for (const id of ["i", "t"]) {
    const c = await page.evaluate((i) => getComputedStyle(document.getElementById(i), "::placeholder").color, id);
    const ratio = (lum("rgb(240,238,232)") + .05) / (lum(c) + .05);
    assert.ok(ratio >= 4.5, `${id} placeholder ${c} is ${ratio.toFixed(2)}:1`);
  }
});
