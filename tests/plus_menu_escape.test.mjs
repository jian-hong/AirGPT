/**
 * Escape closes the + menu and puts focus back on +; with the menu shut, Escape reaches the
 * page's other handlers as before. The handler is cut out of index.html and run in Chromium.
 *   node --test tests/plus_menu_escape.test.mjs
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright");
const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const a = html.indexOf("function closePlusMenu(){");
const b = html.indexOf("function syncPlusSheet(){");
const c = html.indexOf("// Escape closes the + menu first");
const d = html.indexOf("},true);", c) + "},true);".length;
let browser, page;
before(async () => {
  browser = await chromium.launch();
  page = await browser.newPage();
  await page.setContent('<button id="attachBtn" aria-expanded="true">+</button><div id="plusMenu" class="open"><button id="pmItem">x</button></div>');
  await page.evaluate((src) => {
    window.$ = (id) => document.getElementById(id);
    window.other = 0;
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") window.other++; });
    (0, eval)(src);
  }, html.slice(a, b) + (c > 0 ? html.slice(c, d) : ""));
});
after(async () => { await browser.close(); });

test("Escape closes the open + menu, returns focus to +, and nothing else reacts", async () => {
  await page.focus("#pmItem");
  await page.keyboard.press("Escape");
  const r = await page.evaluate(() => [$("plusMenu").hidden, $("attachBtn").getAttribute("aria-expanded"), document.activeElement.id, window.other]);
  assert.deepEqual(r, [true, "false", "attachBtn", 0]);
});

test("Escape with the menu closed still reaches the other handlers", async () => {
  await page.keyboard.press("Escape");
  assert.equal(await page.evaluate(() => window.other), 1);
});
