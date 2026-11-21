/**
 * Round 3b visual checks on the REAL page: starts the app (tests/devkit/run_app.py) and the stand-in
 * model (tests/devkit/stub_llm.py), drives them with Chromium at phone, tablet and laptop sizes.
 *   node --test tests/visual_r3b.test.mjs
 * AIRGPT_ROOT=<other checkout> runs the same checks against another checkout (to see them fail on the base).
 * It writes env.local in that checkout (pointing at the stand-in model) and puts back whatever was there.
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright");
const here = path.resolve(new URL("../", import.meta.url).pathname);
const ROOT = process.env.AIRGPT_ROOT ? path.resolve(process.env.AIRGPT_ROOT) : here;
const DEV = path.join(here, "tests/devkit");

const freePort = () => new Promise((res) => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); }); });
let procs = [], browser, BASE, tmp, envBackup = null, envPath = path.join(ROOT, "env.local");

async function until(fn, ms = 40000) { const t = Date.now(); for (;;) { try { if (await fn()) return; } catch {} if (Date.now() - t > ms) throw new Error("timed out"); await new Promise((r) => setTimeout(r, 300)); } }

before(async () => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "r3b-"));
  const llm = await freePort(), app = await freePort();
  if (fs.existsSync(envPath)) envBackup = fs.readFileSync(envPath);
  fs.writeFileSync(envPath, `OLLAMA_BASE_URL=http://127.0.0.1:${llm}\nOLLAMA_MODEL=stub-model\n`);
  const env = { ...process.env, HF_HUB_OFFLINE: "1", TRANSFORMERS_OFFLINE: "1" };
  procs.push(spawn("python3", [path.join(DEV, "stub_rich.py"), String(llm), path.join(tmp, "req.jsonl")], { env, stdio: "ignore" }));
  procs.push(spawn("python3", [path.join(DEV, "run_app.py"), "--root", ROOT, "--port", String(app), "--data", path.join(tmp, "data")], { env, stdio: "ignore" }));
  BASE = `http://127.0.0.1:${app}`;
  await until(async () => (await fetch(BASE + "/")).ok);
  browser = await chromium.launch();
});
after(async () => {
  try { await browser?.close(); } catch {}
  for (const p of procs) try { p.kill("SIGKILL"); } catch {}
  try { envBackup ? fs.writeFileSync(envPath, envBackup) : fs.rmSync(envPath, { force: true }); } catch {}
  try { fs.rmSync(tmp, { recursive: true, force: true }); } catch {}
});

async function open(w, h, touch = w < 900) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, hasTouch: touch, isMobile: touch });
  const p = await ctx.newPage();
  await p.goto(BASE + "/", { waitUntil: "domcontentloaded" });
  await p.waitForTimeout(2200);
  return { ctx, p };
}
async function reply(p, q) {
  const n = await p.locator('#chat .msg.ai-msg[id^="msg-"]').count();
  await p.fill("#input", q);
  await p.locator(".composer .send").first().click();
  await p.waitForFunction((n) => document.querySelectorAll('#chat .msg.ai-msg[id^="msg-"]').length > n && !document.getElementById("ai-stream"), n, { timeout: 40000 });
  await p.waitForTimeout(500);
}
const overlap = (a, b) => a.x < b.x + b.width - 1 && b.x < a.x + a.width - 1 && a.y < b.y + b.height - 1 && b.y < a.y + a.height - 1;

for (const [w, h] of [[320, 568], [360, 780], [390, 844]]) {
  test(`phone ${w}x${h}: reply uses the width, actions are one row of 44px icons, nothing sits over the text`, async () => {
    const { ctx, p } = await open(w, h);
    await reply(p, "one"); await reply(p, "two"); await reply(p, "three");
    const r = await p.evaluate(() => {
      const box = (e) => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; };
      const last = [...document.querySelectorAll('.msg.ai-msg[id^="msg-"]')].pop();
      const jb = document.getElementById("msgJumpBar");
      return {
        docW: document.documentElement.scrollWidth, jump: jb ? getComputedStyle(jb).display : "none",
        body: box(last.querySelector(".body")),
        btns: [...last.querySelectorAll(".meta button")].map((b) => ({ ...box(b), label: b.getAttribute("aria-label"), title: b.getAttribute("title"), text: b.textContent.trim() })),
      };
    });
    assert.equal(r.docW, w, "no sideways page scroll");
    assert.equal(r.jump, "none", "the reply jump bar is hidden on a phone (it sat over text and code)");
    assert.ok(Math.abs(r.body.x - (w - r.body.x - r.body.width)) <= 4, `reply is centred in the width: left ${r.body.x}, right ${w - r.body.x - r.body.width}`);
    assert.ok(r.body.x <= 14, "no avatar column indenting the reply");
    assert.equal(r.btns.length, 5, "Copy, Reply, Prompt, Fork and Regenerate are all still there");
    assert.deepEqual(r.btns.map((b) => b.label), ["Copy", "Reply", "Prompt", "Fork", "Regenerate"]);
    assert.ok(r.btns.every((b) => b.title), "every action has a hover title");
    assert.equal(new Set(r.btns.map((b) => Math.round(b.y))).size, 1, "one row");
    assert.ok(r.btns.every((b) => b.width >= 44 && b.height >= 44), "44px tap areas: " + JSON.stringify(r.btns.map((b) => [b.width, b.height])));
    for (let i = 0; i < r.btns.length; i++) { for (let j = i + 1; j < r.btns.length; j++) assert.ok(!overlap(r.btns[i], r.btns[j]), "tap areas do not overlap"); assert.ok(!overlap(r.btns[i], r.body), "actions do not sit on the text"); }
    await ctx.close();
  });
}

test("laptop 1280x800: the reply jump bar and the text buttons are unchanged", async () => {
  const { ctx, p } = await open(1280, 800);
  await reply(p, "one"); await reply(p, "two");
  const r = await p.evaluate(() => {
    const last = [...document.querySelectorAll('.msg.ai-msg[id^="msg-"]')].pop();
    return { jump: getComputedStyle(document.getElementById("msgJumpBar")).display, meta: getComputedStyle(last.querySelector(".meta")).display, copy: last.querySelector(".msg-copy").textContent.trim(), av: getComputedStyle(last.querySelector(".av")).display };
  });
  assert.notEqual(r.jump, "none"); assert.notEqual(r.meta, "contents"); assert.equal(r.copy, "Copy"); assert.notEqual(r.av, "none");
  await ctx.close();
});

for (const [w, h] of [[360, 780], [320, 568], [390, 500]]) {
  test(`OpenIDE ${w}x${h}: the hero is visible, the work panel starts folded and opens, the Cortex chip has a 44px tap area`, async () => {
    const { ctx, p } = await open(w, h);
    await p.evaluate(() => showWorkspace("openide")); await p.waitForTimeout(2000);
    const r = await p.evaluate(() => {
      const hint = document.getElementById("openideEmptyHint").getBoundingClientRect();
      const tr = document.getElementById("openideTranscript").getBoundingClientRect();
      const ws = document.getElementById("openideWorkspace").getBoundingClientRect();
      const tog = document.getElementById("openideWorkToggle");
      const chip = document.getElementById("openideCortexChip"); const c = chip.getBoundingClientRect();
      let y0 = 1e9, y1 = -1e9;
      for (let y = c.y + c.height / 2 - 30; y <= c.y + c.height / 2 + 30; y += 1) { const e = document.elementFromPoint(c.x + c.width / 2, y); if (e && (e === chip || chip.contains(e))) { y0 = Math.min(y0, y); y1 = Math.max(y1, y); } }
      return { hintTop: hint.top, hintVisibleBottom: Math.min(hint.bottom, tr.bottom), trTop: tr.top, wsH: ws.height, toggle: !!tog && tog.getBoundingClientRect().height > 0, chipOwn: y1 - y0 + 1, docW: document.documentElement.scrollWidth };
    });
    assert.equal(r.docW, w);
    assert.ok(r.hintTop >= r.trTop - 1 && r.hintVisibleBottom - r.hintTop >= 100, `hero visible: ${JSON.stringify(r)}`);
    assert.ok(r.wsH <= 60, "the work panel starts folded to its tab strip: " + r.wsH);
    assert.ok(r.toggle, "a visible way to open it");
    assert.ok(r.chipOwn >= 44, "Cortex chip owns " + r.chipOwn + "px");
    await p.locator("#openideWorkToggle").click();
    const after = await p.evaluate(() => ({ exp: document.getElementById("openideWorkToggle").getAttribute("aria-expanded"), h: document.getElementById("openideWorkspace").getBoundingClientRect().height, prev: document.getElementById("openidePreviewPane").getBoundingClientRect().height }));
    assert.equal(after.exp, "true"); assert.ok(after.h > 100 && after.prev > 0, "panel opens: " + JSON.stringify(after));
    await ctx.close();
  });
}

test("tablet 820x1180: drawer Search and List icons and the edge tab have 44px tap areas", async () => {
  const { ctx, p } = await open(820, 1180, true);
  await p.locator("#sideCollapseBtn").click(); await p.waitForTimeout(700);
  const r = await p.evaluate(() => {
    const out = {};
    for (const [k, sel] of [["search", '.nav-chats-row .icon-btn[aria-label="Search"]'], ["edge", "#sideCollapseBtn"]]) {
      const e = document.querySelector(sel); const c = e.getBoundingClientRect(); let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
      for (let x = c.x - 20; x <= c.right + 40; x += 1) for (let y = c.y + c.height / 2 - 40; y <= c.y + c.height / 2 + 40; y += 2) { const h = document.elementFromPoint(x, y); if (h && (h === e || e.contains(h))) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); } }
      out[k] = { w: x1 - x0 + 1, h: y1 - y0 + 2 };
    }
    return out;
  });
  assert.ok(r.search.w >= 44 && r.search.h >= 44, "Search icon " + JSON.stringify(r.search));
  assert.ok(r.edge.w >= 44 && r.edge.h >= 44, "edge tab " + JSON.stringify(r.edge));
  await ctx.close();
});

test("knowledge space on a phone: the report button does not sit on Send", async () => {
  const mk = await fetch(BASE + "/api/rag/spaces", { method: "POST", body: JSON.stringify({ name: "Penang launch" }) }).then((r) => r.json());
  const { ctx, p } = await open(390, 844);
  await p.evaluate(async (id) => { await showRagPage(); await ragOpenSpace(id); }, mk.space.id);
  await p.waitForTimeout(1500);
  const r = await p.evaluate(() => {
    const s = document.getElementById("ragAskSend").getBoundingClientRect(), b = document.getElementById("bugReportBtn");
    const bb = b && getComputedStyle(b).display !== "none" ? b.getBoundingClientRect() : null;
    return { send: s, bug: bb, sendOwn: (() => { const hit = document.elementFromPoint(s.x + s.width / 2, s.y + s.height / 2); return hit && (hit.id === "ragAskSend" || hit.closest("#ragAskSend")); })() };
  });
  assert.ok(r.sendOwn, "Send is not covered");
  if (r.bug) assert.ok(!overlap(r.send, r.bug), "report button is clear of Send");
  assert.ok(r.send.width >= 44 && r.send.height >= 44, "Send is 44px");
  await ctx.close();
});
