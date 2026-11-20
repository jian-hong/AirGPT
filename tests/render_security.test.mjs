/**
 * Rendering holds against crafted answers, with the real DOMPurify, marked, KaTeX and Mermaid
 * (from the CDN the page uses) and the page's own functions taken from index.html:
 *   - a Mermaid label cannot take a page id or class (the real composer and buttons stay the real ones)
 *   - <label for="sendBtn"> cannot press a page button, <form>/popover cannot reach one either
 *   - a formula or table cannot make the chat huge or freeze it
 *   - ordinary answers (tables, code, maths, flowcharts, links) still render
 *   node --test tests/render_security.test.mjs
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const html = fs.readFileSync(process.env.INDEX_HTML || new URL("../index.html", import.meta.url), "utf8");

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
const PAGE_IDS = ["settingsModal", "input", "chat", "sendBtn", "composer", "settingsBtn"];
let browser, page;
before(async () => {
  browser = await chromium.launch();
  page = await browser.newPage({ viewport: { width: 1000, height: 700 } });
  await page.setContent(`<!doctype html><body style="margin:0">
    <div id="settingsModal" class="modal-backdrop">S</div><button id="settingsBtn">settings</button>
    <textarea id="input"></textarea><div id="composer"></div><button id="sendBtn" onclick="window.sent=(window.sent||0)+1">send</button>
    <div id="chat" class="ai-block"></div></body>`);
  await page.addStyleTag({ url: CDN("katex@0.16.11/dist/katex.min.css") });
  for (const u of ["dompurify@3.1.6/dist/purify.min.js", "marked@12.0.2/marked.min.js", "katex@0.16.11/dist/katex.min.js", "mermaid@11.6.0/dist/mermaid.min.js"]) {
    await page.addScriptTag({ url: CDN(u) });
  }
  await page.evaluate(() => { window.esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); });
  const names = ["sanitizeHtml", "mdFallback", "renderMd", "ragSafeMoney", "ragLinkCiteChips", "ragMdHtml", "initMermaid", "sanitizeMermaidSrc", "cleanMermaidSvg", "renderMermaidIn"];
  const src = names.filter((n) => new RegExp("^(async )?function " + n + "\\(", "m").test(html)).map(grab).join("\n");
  const head = (/^const _KATEX_SAFE=[\s\S]*?^function texOk.*$/m.exec(html) || /^const _KATEX_SAFE=.*$/m.exec(html))[0];
  await page.addScriptTag({ content: head + "\nlet _mermaidReady=false;\n" + src + "\nwindow.renderMd=renderMd;window.ragMdHtml=ragMdHtml;window.renderMermaidIn=renderMermaidIn;" });
});
after(async () => { await browser.close(); });

// Put an answer into #chat the way the page does and draw its diagrams.
const show = (fn, md) => page.evaluate(async ([fn, md]) => {
  const chat = document.getElementById("chat");
  chat.innerHTML = fn === "rag" ? ragMdHtml(md, "s1", []) : renderMd(md);
  await renderMermaidIn(chat);
  return chat.innerHTML.length;
}, [fn, md]);
const hostIntact = () => page.evaluate((ids) => ids.map((i) => {
  const all = document.querySelectorAll('[id="' + i + '"]');
  const first = document.getElementById(i);
  return { id: i, count: all.length, outside: first && !first.closest("#chat") && first.id === i && i !== "chat" ? true : i === "chat" ? first === document.querySelector("body > #chat") : false };
}), PAGE_IDS);

const MERMAID_ATTACK = [
  "```mermaid", "graph TD",
  `A["<div id='settingsModal' class='modal-backdrop open'>boom</div>"] --> B["<span id='input' class='msg'>x</span><img src=x id='chat' name='body'>"]`,
  `C["<button id='sendBtn'>b</button><input id='composer'>"]`,
  `subgraph S["<b id='settingsBtn'>t</b>"]`, `D -->|"<i id='sendBtn'>e</i>"| E`, "end", "```", ""].join("\n");

for (const fn of ["main", "rag"]) {
  test(`${fn}: a Mermaid label cannot take a page id or class`, async () => {
    await page.evaluate(() => { window.sent = 0; });
    await show(fn, MERMAID_ATTACK);
    assert.ok(await page.evaluate(() => !!document.querySelector("#chat svg")), "the diagram is still drawn");
    for (const r of await hostIntact()) assert.equal(r.count, 1, r.id + " must exist once: " + JSON.stringify(r));
    assert.equal(await page.evaluate(() => document.getElementById("input").tagName), "TEXTAREA");
    assert.equal(await page.evaluate(() => document.getElementById("sendBtn").tagName), "BUTTON");
    assert.equal(await page.evaluate(() => document.querySelectorAll("#chat .modal-backdrop, #chat .msg, #chat .open").length), 0);
    assert.equal(await page.evaluate(() => document.querySelectorAll("#chat input, #chat button, #chat img, #chat foreignObject [id], #chat foreignObject [name]").length), 0);
    await page.click("#sendBtn");
    assert.equal(await page.evaluate(() => window.sent), 1, "a real click reaches the real button");
  });
}

test("ordinary diagrams still draw with their text and shape", async () => {
  await show("main", "```mermaid\nflowchart LR\n  A[Start] --> B{Choice}\n  B -->|yes| C[Do it]\n  B -->|no| D((End))\n  subgraph G[Group]\n  C --> D\n  end\n  classDef hot fill:#f00\n  class C hot\n```\n");
  const r = await page.evaluate(() => ({ text: document.querySelector("#chat svg").textContent, nodes: document.querySelectorAll("#chat svg .node").length, edges: document.querySelectorAll("#chat svg path.flowchart-link").length, marker: [...document.querySelectorAll("#chat svg path[marker-end]")].every((p) => { const m = /url\(#([^)]+)\)/.exec(p.getAttribute("marker-end")); return m && document.getElementById(m[1]); }) }));
  for (const w of ["Start", "Choice", "yes", "no", "End", "Group", "Do it"]) assert.ok(r.text.includes(w), w);
  assert.ok(r.nodes >= 4 && r.edges >= 3, JSON.stringify(r));
  assert.ok(r.marker, "arrow heads still point at their markers");
  await show("main", "```mermaid\nsequenceDiagram\n A->>B: Hi\n B-->>A: ok\n```\n");
  assert.ok(await page.evaluate(() => /Hi/.test(document.querySelector("#chat svg").textContent) && [...document.querySelectorAll("#chat svg [marker-end]")].every((p) => { const m = /url\(#([^)]+)\)/.exec(p.getAttribute("marker-end")); return m && document.getElementById(m[1]); })));
  await show("main", '```mermaid\npie title Pets\n "Dogs" : 386\n "Cats" : 85\n```\n');
  assert.ok(await page.evaluate(() => /Dogs/.test(document.querySelector("#chat svg").textContent)));
});

const LABEL_ATTACKS = [
  '<label for="sendBtn">Click to see the answer</label>', '<label for="settingsBtn">x</label>', '<label for="bgTasksTopBtn">x</label>',
  '<label for="clearAllHistoryBtn">x</label>', '<label for="ragAskSend">x</label>',
  '<form id="f"><button>go</button></form><button form="f" formaction="http://evil.test/">x</button>',
  '<button popovertarget="settingsModal">x</button><div popover id="p">x</div>', '<input list="sendBtn">',
];
for (const fn of ["main", "rag"]) {
  test(`${fn}: a message cannot point at a page element by id`, async () => {
    for (const v of LABEL_ATTACKS) {
      await page.evaluate(() => { window.sent = 0; });
      await show(fn, v);
      const left = await page.evaluate(() => [...document.querySelectorAll("#chat *")].flatMap((e) => ["for", "form", "formaction", "popover", "popovertarget", "list"].filter((a) => e.hasAttribute(a)).map((a) => e.localName + "[" + a + "]")));
      assert.deepEqual(left, [], v);
      const t = page.locator("#chat p, #chat label").first();
      if (await t.count()) await t.click({ position: { x: 3, y: 3 }, force: true }).catch(() => {});
      assert.equal(await page.evaluate(() => window.sent), 0, "no page button pressed by " + v);
    }
  });
}

const BOMBS = {
  gdef: "a $\\gdef\\arraystretch{5000}\\begin{matrix}a\\\\b\\end{matrix}$ b",
  def: "$$\\def\\arraystretch{100000}\\begin{array}{c}a\\\\b\\end{array}$$",
  renew: "$\\renewcommand{\\arraystretch}{9999}\\begin{matrix}a\\\\b\\end{matrix}$",
  edef: "$\\edef\\x{1}\\x$ $\\xdef\\y{1}$ $\\let\\z=1$",
  table: '<table width="99999" height="99999" cellpadding="9999" cellspacing="9999" border="9999"><tr><td height="99999" width="99999">x</td></tr></table>',
  marquee: '<marquee width="99999" height="99999">x</marquee>',
  long: "$$" + "\\underbrace{".repeat(20000) + "x" + "}".repeat(20000) + "$$",
  long2: "$$" + "x+".repeat(50000) + "x$$",
};
for (const fn of ["main", "rag"]) {
  test(`${fn}: a crafted formula or table cannot make the chat huge or freeze it`, async () => {
    for (const [k, v] of Object.entries(BOMBS)) {
      const t0 = Date.now();
      await show(fn, v);
      const ms = Date.now() - t0;
      const h = await page.evaluate(() => Math.round(document.getElementById("chat").getBoundingClientRect().height));
      assert.ok(h < 1500, k + " made the answer " + h + " px tall");
      assert.ok(ms < 2500, k + " took " + ms + " ms");
    }
  });
}

test("ordinary maths, tables, code and links still render", async () => {
  const md = [
    "Inline $\\frac{a}{b} + \\sqrt{x}$ and $\\text{rate} \\color{red}{x}$.", "",
    "$$\\begin{aligned} a &= b + c \\\\ d &= e \\end{aligned}$$", "",
    "$$\\begin{pmatrix} 1 & 2 \\\\ 3 & 4 \\end{pmatrix}$$", "",
    "| A | B |", "|---|---|", "| 1 | 2 |", "",
    "```js\nconst x = 1;\n```", "", "[link](https://example.com/page)", "",
  ].join("\n");
  await show("main", md);
  const r = await page.evaluate(() => ({
    katex: document.querySelectorAll("#chat .katex").length, display: document.querySelectorAll("#chat .katex-display").length,
    err: document.querySelectorAll("#chat .katex-error").length, td: document.querySelectorAll("#chat table td").length,
    code: !!document.querySelector("#chat pre code"), a: document.querySelector("#chat a")?.getAttribute("href"),
  }));
  assert.ok(r.katex >= 4 && r.display === 2 && r.err === 0 && r.td === 2 && r.code && r.a === "https://example.com/page", JSON.stringify(r));
});
