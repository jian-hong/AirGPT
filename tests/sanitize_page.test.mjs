/**
 * sanitizeHtml / renderMd / ragMdHtml from index.html, run with the real DOMPurify and marked
 * (fetched from the same CDN the page uses; the test fails loudly if it cannot reach it).
 * A request listener proves nothing leaves for evil.test. Run with:
 *   node --test tests/sanitize_page.test.mjs
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
let browser, page, hits;
before(async () => {
  browser = await chromium.launch();
  page = await browser.newPage();
  hits = [];
  await page.route(/evil\.test/, (r) => { hits.push(r.request().url()); r.abort(); });
  await page.setContent("<!doctype html><body></body>");
  await page.addScriptTag({ url: CDN("dompurify@3.1.6/dist/purify.min.js") });
  await page.addScriptTag({ url: CDN("marked@12.0.2/marked.min.js") });
  await page.evaluate(() => {
    window.esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    // Stand-in maths: styled output like the real KaTeX, so the round trip is checked.
    window.katex = { renderToString: (t, o) => `<span class="katex" style="height:1em;color:red"><span style="top:-3px">${window.esc(t)}</span></span>` };
  });
  const src = ["sanitizeHtml", "mdFallback", "renderMd", "ragSafeMoney", "ragLinkCiteChips", "ragMdHtml"].filter((n) => new RegExp("^function " + n + "\\(", "m").test(html)).map(grab).join("\n");
  await page.addScriptTag({ content: /^const _KATEX_SAFE=[\s\S]*?^function texOk.*$/m.exec(html)[0] + "\n" + src + "\nwindow.sanitizeHtml=sanitizeHtml;window.renderMd=renderMd;window.ragMdHtml=ragMdHtml;" });
});
after(async () => { await browser.close(); });

const show = (fn, md) => page.evaluate(([fn, md]) => {
  const d = document.createElement("div");
  d.innerHTML = fn === "rag" ? ragMdHtml(md, "s1", []) : renderMd(md);
  document.body.appendChild(d);
  return { html: d.innerHTML, fixed: !!d.querySelector("[style]") };
}, [fn, md]);

const ATTACKS = {
  overlay: '<div style="position:fixed;top:0;left:0;width:100vw;height:100vh;background:#fff">Session expired</div>',
  stylebg: '<div style="background:url(http://evil.test/stylebg)">x</div>',
  tablebg: '<table background="http://evil.test/tablebg"><tr><td background="http://evil.test/tdbg">x</td></tr></table>',
  listimg: '<ul style="list-style-image:url(http://evil.test/listimg)"><li>x</li></ul>',
  srcset: '<img srcset="http://evil.test/srcset 1x">',
  svgimg: '<svg><image href="http://evil.test/svgimg"/></svg>',
  svgstyle: '<svg><style>*{background:url(http://evil.test/svgstyle)}</style><rect width=10 height=10 fill="url(http://evil.test/svgfill)"/></svg>',
  poster: '<video poster="http://evil.test/poster"></video>',
  styletag: "<style>@import 'http://evil.test/imp'; a{background:url(http://evil.test/css)}</style><p>t</p>",
};

for (const fn of ["main", "rag"]) {
  test(`${fn}: no style or address-bearing attribute survives, nothing is requested`, async () => {
    hits.length = 0;
    for (const [k, v] of Object.entries(ATTACKS)) {
      const r = await show(fn, v);
      assert.ok(!/\sstyle=|background=|srcset=|poster=|url\(|@import/i.test(r.html), k + ": " + r.html);
    }
    await page.waitForTimeout(600);
    assert.deepEqual(hits, []);
  });
}

test("main: links stay clickable and javascript: links are dead", async () => {
  const r = await show("main", "[ok](https://example.com) [bad](javascript:alert(1))");
  assert.match(r.html, /<a href="https:\/\/example.com">ok<\/a>/);
  assert.ok(!/javascript:/i.test(r.html), r.html);
});

test("main: our own maths keeps its styles, model markup does not", async () => {
  const r = await show("main", 'Inline $a+b$ and\n\n$$x^2$$\n\n<div style="position:fixed">evil</div>');
  assert.equal((r.html.match(/class="katex" style="height:1em;color:red"/g) || []).length, 2, r.html);
  assert.ok(!/position:fixed/.test(r.html), r.html);
  assert.ok(!/KXMATHTOKEN/.test(r.html));
});

test("main: tables and diagrams still come out", async () => {
  const r = await show("main", "| a | b |\n|---|---|\n| 1 | 2 |\n\n```mermaid\ngraph TD; A-->B\n```");
  assert.match(r.html, /<table>/);
  assert.match(r.html, /class="mermaid" data-mm-src=/);
});

test("main: maths tokens in attributes are dropped and a forged token is just text", async () => {
  const r = await show("main", '<a href="#" title="$x$">q</a> and $y$ KXMATHTOKEN0ENDTOKEN');
  assert.ok(!/title="[^"]*katex/.test(r.html) && !/ katex"/.test(r.html), r.html);
  assert.equal((r.html.match(/class="katex"/g) || []).length, 1, r.html);
  assert.ok(r.html.includes("KXMATHTOKEN0ENDTOKEN"), r.html);
});
