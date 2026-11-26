/**
 * ui/sanitize.js is the cleaner used for chat messages when DOMPurify is missing.
 * It needs a real HTML parser, so the tests run it inside headless Chromium (the
 * same Playwright the browser tests use). Run with:
 *   node --test tests/sanitize.test.mjs
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const SCRIPT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "ui", "sanitize.js");

let browser, page;
before(async () => {
  browser = await chromium.launch();
  page = await browser.newPage();
  await page.setContent("<!doctype html><body></body>");
  await page.addScriptTag({ path: SCRIPT });
});
after(async () => { await browser.close(); });

const clean = (html) => page.evaluate((h) => window.AirSanitize.clean(h), html);

/** Insert the cleaned HTML into the page, click every link, and report what ran. */
async function runIt(html) {
  return page.evaluate((h) => {
    window.__ran = 0;
    const box = document.createElement("div");
    box.innerHTML = window.AirSanitize.clean(h);
    document.body.appendChild(box);
    box.querySelectorAll("a").forEach((a) => a.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })));
    const out = { ran: window.__ran, html: box.innerHTML };
    box.remove();
    return out;
  }, html);
}

test("SVG animation that sets href to javascript: is removed", async () => {
  const r = await runIt('<svg width=200 height=100><a><animate attributeName=href values="javascript:window.__ran=1" /><text>x</text></a></svg>' +
    '<a href="#"><set attributeName=href to="javascript:window.__ran=2"/>t</a>');
  assert.equal(r.ran, 0);
  assert.ok(!/svg|animate|<set|javascript/i.test(r.html), r.html);
});

test("event attributes and script-like elements are removed", async () => {
  const out = await clean('<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" onerror="alert(1)"><p onclick="x()" onmouseover=y()>hi</p>' +
    "<script>alert(1)</script><iframe src=//e.example></iframe><object data=x></object><embed src=x><style>a{}</style>");
  assert.ok(!/ on\w+=|<script|<iframe|<object|<embed|<style/i.test(out), out);
  assert.match(out, /<p>hi<\/p>/);
});

test("forms and their controls are removed", async () => {
  const out = await clean('<form action="https://evil.example/x"><input name=a><button formaction=//e>go</button><textarea>t</textarea><select><option>1</select></form>');
  assert.ok(!/<form|<input|<button|<textarea|<select|<option|formaction|action=/i.test(out), out);
});

test("only http, https, mailto and relative links survive, even when disguised", async () => {
  const bad = ["javascript:alert(1)", " JaVaScRiPt:alert(1)", "java\tscript:alert(1)", "java&#10;script:alert(1)",
    "data:text/html,<script>alert(1)</script>", "vbscript:x", "file:///etc/passwd", "&#106;avascript:alert(1)"];
  for (const u of bad) {
    const out = await clean(`<a href="${u}">x</a>`);
    assert.ok(!/href/i.test(out), `${u} -> ${out}`);
  }
  for (const u of ["http://a.example/x", "https://a.example/x?y=1#z", "mailto:a@b.example", "/local/path", "rel/path.html", "#frag", "?q=1"]) {
    const out = await clean(`<a href="${u}">x</a>`);
    assert.match(out, /href=/, `${u} -> ${out}`);
  }
});

test("images allow http, https, relative and data:image, nothing else", async () => {
  const bad = ["javascript:alert(1)", "data:text/html;base64,PHNjcmlwdD4=", "data:image/svg+xml;base64,PHN2Zz4=", "mailto:a@b.example", "ftp://x/y.png"];
  for (const u of bad) {
    const out = await clean(`<img src="${u}">`);
    assert.ok(!/src=/i.test(out), `${u} -> ${out}`);
  }
  for (const u of ["https://a.example/p.png", "/data/x.png", "data:image/png;base64,iVBORw0KGgo="]) {
    assert.match(await clean(`<img src="${u}" alt="a">`), /src=/, u);
  }
});

test("style attributes are dropped", async () => {
  const out = await clean('<div style="background:url(https://evil.example/leak)">s</div><p style="position:fixed">p</p>');
  assert.ok(!/style/i.test(out), out);
  assert.match(out, /s<\/div>/);
});

test("math and mutation-style payloads do not survive", async () => {
  const out = await clean('<math><mtext><table><mglyph><style><img src=x onerror=alert(1)></style></mglyph></table></mtext></math>' +
    "<noscript><p title=\"</noscript><img src=x onerror=alert(1)>\"></noscript>");
  assert.ok(!/onerror|<math|<style/i.test(out), out);
});

test("links that open a new tab get rel noopener", async () => {
  assert.match(await clean('<a href="https://a.example" target="_blank">x</a>'), /rel="noopener noreferrer"/);
});

test("normal Markdown output passes through unchanged in meaning", async () => {
  const html = '<h2>Title</h2><p>A <strong>bold</strong> and <em>soft</em> <code>x</code> word.</p><ul><li>one</li><li>two</li></ul>' +
    '<ol start="3"><li>c</li></ol><blockquote><p>q</p></blockquote><pre><code class="language-js">let a = 1;\n</code></pre>' +
    '<table><thead><tr><th>a</th></tr></thead><tbody><tr><td colspan="2">1</td></tr></tbody></table><hr><p><a href="https://a.example">link</a></p>';
  assert.equal(await clean(html), html);
});

test("unknown harmless tags keep their text", async () => {
  assert.equal(await clean("<foo>kept <b>bold</b></foo>"), "kept <b>bold</b>");
});

test("empty and non-string input give an empty string", async () => {
  assert.equal(await clean(""), "");
  assert.equal(await page.evaluate(() => window.AirSanitize.clean(null)), "");
});

// The page runs buttons through data-call="fnName". A model reply must never be able to
// carry those attributes, and the dispatcher must never reach a browser built-in like eval.
import { readFileSync } from "node:fs";
const INDEX = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "index.html"), "utf8");

test("message sanitizer drops data-* attributes so data-call cannot be forged", () => {
  const m = INDEX.match(/function sanitizeHtml\(html\)\{[\s\S]*?\n\}/);
  assert.ok(m, "sanitizeHtml not found");
  assert.match(m[0], /ALLOW_DATA_ATTR:false/);
});

test("data-call dispatcher refuses browser built-ins such as eval", async () => {
  const m = INDEX.match(/function _pageFn\(n\)\{[\s\S]*?\n\}/);
  assert.ok(m, "_pageFn not found");
  const r = await page.evaluate((src) => {
    window.myPageFn = function () { return 1; };
    const _pageFn = new Function(src + "; return _pageFn;")();
    return [_pageFn("eval"), _pageFn("alert"), _pageFn("Function"), _pageFn("myPageFn") === window.myPageFn, _pageFn("nope")];
  }, m[0]);
  assert.deepEqual(r, [null, null, null, true, null]);
});

test("fallback cleaner drops id, name and page classes, keeps the code language", async () => {
  const out = await clean('<div id="input" class="modal-backdrop">a</div><a name="x" id="y">b</a><code class="language-js evil">c</code><span class="modal-backdrop">d</span>');
  assert.ok(!/\s(id|name)=/.test(out), out);
  assert.ok(!/modal-backdrop|evil/.test(out), out);
  assert.match(out, /<code class="language-js">c<\/code>/);
});

test("fallback cleaner drops for, form, popover, list and size attributes", async () => {
  const out = await clean('<label for="sendBtn">x</label><table width="99999" height="99999" cellpadding="9" border="9"><tr><td height="9" width="9">y</td></tr></table>' +
    '<span popover popovertarget="a" list="b" form="c" formaction="http://evil.test/">z</span><marquee>m</marquee>');
  assert.ok(!/\s(for|form|formaction|popover|popovertarget|list|width|height|cellpadding|border)=/i.test(out), out);
  assert.ok(!/marquee/i.test(out), out);
  assert.match(out, /x/); assert.match(out, /y/); assert.match(out, /z/);
});
