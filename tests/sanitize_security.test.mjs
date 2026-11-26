/**
 * Security findings pm-agents.1 and pm-security.0: untrusted markup must not take over page ids or
 * classes, and maths, svg and diagram tokens must not be able to blow the page up.
 * Uses the real DOMPurify, marked and KaTeX from the CDN the page uses.
 *   node --test tests/sanitize_security.test.mjs
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
function grab(name) {
  const m = new RegExp("^(async )?function " + name + "\\(", "m").exec(html);
  assert.ok(m, name + " not found");
  let depth = 0;
  for (let j = html.indexOf("{", m.index); j < html.length; j++) {
    if (html[j] === "{") depth++;
    else if (html[j] === "}" && --depth === 0) return html.slice(m.index, j + 1);
  }
  throw new Error("unbalanced " + name);
}
const CDN = (u) => "https://cdn.jsdelivr.net/npm/" + u;
let browser, page;
before(async () => {
  browser = await chromium.launch();
  page = await browser.newPage();
  await page.setContent('<!doctype html><body><input id="input"><div id="chat"></div></body>');
  await page.addScriptTag({ url: CDN("dompurify@3.1.6/dist/purify.min.js") });
  await page.addScriptTag({ url: CDN("marked@12.0.2/marked.min.js") });
  await page.addScriptTag({ url: CDN("katex@0.16.11/dist/katex.min.js") });
  await page.evaluate(() => { window.esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); });
  const src = ["sanitizeHtml", "mdFallback", "renderMd", "ragSafeMoney", "ragLinkCiteChips", "ragMdHtml"].filter((n) => new RegExp("^function " + n + "\\(", "m").test(html)).map(grab).join("\n");
  const ksafe = /^const _KATEX_SAFE=[\s\S]*?^function texOk.*$/m.exec(html);
  assert.ok(ksafe, "_KATEX_SAFE not found");
  await page.addScriptTag({ content: ksafe[0] + "\n" + src + "\nwindow.renderMd=renderMd;window.ragMdHtml=ragMdHtml;" });
});
after(async () => { await browser.close(); });
const out = (fn, md) => page.evaluate(([fn, md]) => (fn === "rag" ? ragMdHtml(md, "s1", []) : renderMd(md)), [fn, md]);

const IDS = [
  '<div id="input">x</div>', '<p id="chat">x</p>', '<span id="cortexStopBtn">x</span>', '<div id="bgTasksPanel">x</div>',
  '<a name="input">x</a>', '<img name="input" alt="x">', '<div class="modal-backdrop">x</div>', '<p id="location">x</p>',
  '<table name="x"><tr><td id="y">x</td></tr></table>',
];
for (const fn of ["main", "rag"]) {
  test(`${fn}: untrusted id, name and page classes are dropped`, async () => {
    for (const v of IDS) {
      const r = await out(fn, v);
      assert.ok(!/\s(id|name)=/i.test(r), v + " -> " + r);
      assert.ok(!/modal-backdrop/.test(r), v + " -> " + r);
    }
  });
}
test("main: the composer still answers after an answer carried id=input", async () => {
  const ok = await page.evaluate(() => {
    const d = document.createElement("div");
    d.innerHTML = renderMd('<input id="input"><div id="input">x</div>');
    document.body.prepend(d);
    const e = document.getElementById("input");
    d.remove();
    return e && e.tagName === "INPUT" && typeof e.value === "string";
  });
  assert.ok(ok);
});
test("main: code language class and ordinary Markdown survive", async () => {
  const r = await out("main", "```js\nlet a=1\n```\n\n| a | b |\n|---|:-:|\n| 1 | 2 |\n\n[x](https://example.com)");
  assert.match(r, /class="language-js"/);
  assert.match(r, /<table>/);
  assert.match(r, /<a href="https:\/\/example.com">x<\/a>/);
});

const BIG = ["$\\rule{99999em}{99999em}$", "$$\\rule{99999em}{99999em}$$", "$\\kern{99999em}x$", "$\\hspace{99999em}x$", "$\\raisebox{99999em}{x}$", "$\\rule{1em}{99999em}$"];
for (const fn of ["main", "rag"]) {
  test(`${fn}: huge maths sizes are refused`, async () => {
    for (const md of BIG) {
      const r = await out(fn, md);
      const bad = /(style|width|height)="[^"]*(?<![0-9.])[0-9]{3,}(\.[0-9]+)?em/.exec(r); assert.ok(!bad, md + " -> " + (bad && r.slice(bad.index - 50, bad.index + 150)));
    }
  });
}
test("main: macro bombs are refused", async () => {
  const r = await out("main", "$\\def\\a{\\a\\a}\\a$");
  assert.ok(r.length < 5000, "length " + r.length);
});
test("main: ordinary maths still renders", async () => {
  const r = await out("main", "Inline $x^2+\\frac{1}{2}$ and\n\n$$\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}$$ and $\\rule{2em}{1em}$");
  assert.equal((r.match(/class="katex"/g) || []).length, 3, r.slice(0, 400));
  assert.ok(!/katex-error/.test(r));
});
test("main: raw svg size is not kept", async () => {
  const r = await out("main", '<svg width=9999 height=9999 viewBox="0 0 10 10"><rect width=5 height=5 /></svg>');
  assert.ok(!/(width|height)="?9999/.test(r), r);
});
test("main: raw img and svg sizes are not kept", async () => {
  const r = await out("main", '<img src="x.png" width=99999 height=99999 alt="a">');
  assert.ok(!/(width|height)=/.test(r), r);
});
test("main: forged diagram tokens are not expanded", async () => {
  const forged = "MMDIAGRAMTOKEN0ENDTOKEN";
  const a = await out("main", forged);
  assert.ok(!/class="mermaid"/.test(a), a);
  const b = await out("main", "```mermaid\ngraph TD; A-->B\n```\n\ntext " + forged + '\n\n<a title="' + forged + '">k</a>');
  assert.equal((b.match(/class="mermaid"/g) || []).length, 1, b);
});
test("main: a real diagram still comes out", async () => {
  const r = await out("main", "```mermaid\ngraph TD; A-->B\n```");
  assert.match(r, /<div class="mermaid" data-mm-src="graph TD; A--&gt;B">/);
});
