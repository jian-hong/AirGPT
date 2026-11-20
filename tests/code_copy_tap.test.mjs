/**
 * The code block Copy button on a touch screen: every corner of a 44x44 box around it must
 * tap it. The code block clips anything past its edge and the reply rail sits over its right
 * side, so the invisible tap layer used to be cut off.   node --test tests/code_copy_tap.test.mjs
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
let browser;
after(async () => { await browser?.close(); });

for (const [w, h] of [[320, 568], [390, 844], [820, 1180]]) {
  for (const theme of ["dark", "light", ""]) {
    test(`touch ${w}px ${theme || "glass"}: all corners of a 44x44 box around Copy tap Copy`, async () => {
      browser ||= await chromium.launch();
      const ctx = await browser.newContext({ viewport: { width: w, height: h }, hasTouch: true, isMobile: true });
      const page = await ctx.newPage();
      await page.setContent(`<!doctype html><html><head><meta name="viewport" content="width=device-width"><style>${inline}</style><style>${linked}</style></head>
<body class="${theme ? "theme-" + theme : ""}"><div class="chat" style="padding:20px 14px;position:relative"><div class="msg ai-msg" style="position:relative"><div class="body">
<pre data-cb><div class="cb-bar"><span class="cb-lang">js</span><button class="cb-copy" type="button">Copy</button></div><code>const answer = 42;
console.log(answer);</code></pre></div></div>
<div id="rail" style="position:fixed;z-index:22;right:14px;top:0;bottom:0;width:22px;pointer-events:auto"></div></div></body></html>`);
      const r = await page.evaluate(() => {
        const e = document.querySelector(".cb-copy"), b = e.getBoundingClientRect(), cx = b.x + b.width / 2, cy = b.y + b.height / 2, miss = [];
        for (const [dx, dy] of [[-21, -21], [21, -21], [-21, 21], [21, 21], [0, -21], [0, 21], [-21, 0], [21, 0]]) {
          const hit = document.elementFromPoint(cx + dx, cy + dy);
          if (!(hit && (hit === e || e.contains(hit)))) miss.push(dx + "," + dy + " " + (hit && (hit.id || hit.className || hit.tagName)));
        }
        return { miss, h: b.height };
      });
      await ctx.close();
      assert.deepEqual(r.miss, []);
      assert.ok(r.h < 44, "the button keeps its small look: " + r.h);
    });
  }
}
