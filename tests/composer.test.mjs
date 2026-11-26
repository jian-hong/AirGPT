/**
 * Behaviour tests for the message box pieces of index.html (counter, Return rule,
 * drafts, suggestion menu Enter rule). Same method as chat_shell.test.mjs.
 *   node --test tests/composer.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
function grab(name) {
  const m = new RegExp("^(async )?function " + name + "\\(", "m").exec(html);
  assert.ok(m, "function " + name + " not found in index.html");
  let i = html.indexOf("{", m.index), depth = 0;
  for (let j = i; j < html.length; j++) {
    if (html[j] === "{") depth++;
    else if (html[j] === "}" && --depth === 0) return html.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces in " + name);
}
function load(names, globals, pre = "") {
  const ctx = vm.createContext(globals);
  vm.runInContext(pre + "\n" + names.map(grab).join("\n"), ctx);
  return ctx;
}

test("the counter stays hidden until the message nears the limit, then names the cut", () => {
  const c = load(["charCountText"], {}, "const INPUT_LIMIT=6000, INPUT_WARN_AT=5000;");
  assert.equal(c.charCountText(100), "");
  assert.equal(c.charCountText(4999), "");
  assert.equal(c.charCountText(5200), "5,200 / 6,000");
  assert.equal(c.charCountText(6000), "6,000 / 6,000");
  assert.match(c.charCountText(20000), /^20,000 \/ 6,000\. Only the first 6,000 will be read\.$/);
});

test("Return sends on a desktop, makes a new line on a touch screen, never while composing", () => {
  const mk = coarse => load(["enterSends", "coarsePointer", "imeBusy"], { matchMedia: () => ({ matches: coarse }) });
  const key = (o = {}) => ({ key: "Enter", shiftKey: false, isComposing: false, keyCode: 13, ...o });
  assert.equal(mk(false).enterSends(key()), true);
  assert.equal(mk(false).enterSends(key({ shiftKey: true })), false);
  assert.equal(mk(false).enterSends(key({ isComposing: true })), false);
  assert.equal(mk(false).enterSends(key({ keyCode: 229 })), false);
  assert.equal(mk(true).enterSends(key()), false);
  assert.equal(mk(false).enterSends({ key: "a" }), false);
});

function draftCtx() {
  const store = {};
  const g = {
    localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } },
    setTimeout, clearTimeout,
    window: { addEventListener() {} },
    $: () => g.box,
    box: { value: "" },
    autoGrowInput() {}, updateSendVisibility() {},
    currentSession: 7, currentMode: () => "general",
  };
  const c = load(["draftKey", "saveComposerDraft", "clearComposerDraft", "restoreComposerDraft", "_draftWrite", "_draftRead"], g,
    "let composerDraftByKey={}; const DRAFT_PREFIX='airgpt_draft:',DRAFT_MAX=20000; const _draftTimers={};");
  return { c, g, store };
}

test("a draft is written to storage after a pause, keyed by chat, and restored", async () => {
  const { c, g, store } = draftCtx();
  g.box.value = "half written";
  c.saveComposerDraft();
  assert.equal(store["airgpt_draft:s:7"], undefined, "written only after the debounce");
  await new Promise(r => setTimeout(r, 450));
  assert.equal(store["airgpt_draft:s:7"], "half written");
  // a fresh page: memory empty, storage kept
  const fresh = draftCtx(); fresh.g.localStorage.setItem("airgpt_draft:s:7", "half written");
  fresh.c.restoreComposerDraft();
  assert.equal(fresh.g.box.value, "half written");
});

test("opening a chat with no draft empties the box instead of keeping the last chat's text", () => {
  const { c, g } = draftCtx();
  g.box.value = "text from another chat"; g.currentSession = 9;
  c.restoreComposerDraft();
  assert.equal(g.box.value, "");
});

test("a cleared draft is removed from storage and a broken storage does not throw", async () => {
  const { c, g, store } = draftCtx();
  g.box.value = "x"; c.saveComposerDraft(); await new Promise(r => setTimeout(r, 450));
  c.clearComposerDraft("s:7");
  assert.equal(store["airgpt_draft:s:7"], undefined);
  g.localStorage.setItem = () => { throw new Error("quota"); };
  g.box.value = "y"; c.saveComposerDraft(); await new Promise(r => setTimeout(r, 450)); // must not throw
});

test("the suggestion menu takes Enter only after an arrow key or when the word starts the box", () => {
  const mk = (value, start, nav) => {
    const ev = k => ({ key: k, target: st.el, isComposing: false, keyCode: 13, prevented: false, preventDefault() { this.prevented = true; }, stopPropagation() {} });
    const st = { open: true, el: { value }, start, items: [{}], active: 0, nav };
    const calls = [];
    const c = load(["_acOnKey"], { _acState: st, imeBusy: e => !!e.isComposing, _acPick: i => calls.push("pick"), _acClose: () => calls.push("close"), _acHighlight() {}, _acRender() {} });
    return { run: k => { const e = ev(k); c._acOnKey(e); return { e, calls }; } };
  };
  let r = mk("please explain the /rag", 19, false).run("Enter");
  assert.deepEqual(r.calls, ["close"]); assert.equal(r.e.prevented, false, "Enter must go on to send");
  r = mk("/rag", 0, false).run("Enter");
  assert.deepEqual(r.calls, ["pick"]); assert.equal(r.e.prevented, true);
  r = mk("use the /", 8, true).run("Enter");
  assert.deepEqual(r.calls, ["pick"]);
  r = mk("use the /", 8, false).run("Tab");
  assert.deepEqual(r.calls, ["pick"]);
});
