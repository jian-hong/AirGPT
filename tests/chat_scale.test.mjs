/**
 * Behaviour tests for the long-chat pieces of index.html: the small chat cache, adding
 * only new messages, and how often the page polls. Run with:
 *   node --test tests/chat_scale.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

function grab(name) {
  const m = new RegExp("^(async )?function " + name + "\\(", "m").exec(html);
  assert.ok(m, "function " + name + " not found in index.html");
  let i = html.indexOf("{", m.index);
  let depth = 0;
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

test("the chat cache keeps only the last 8 chats, newest use last", () => {
  const ctx = load(["chatCachePut"], {}, "var chatCacheBySession={};const CHAT_CACHE_MAX=8, chatCacheOrder=[];");
  for (let id = 1; id <= 12; id++) ctx.chatCachePut(id, { by_date: [], id });
  assert.deepEqual(Object.keys(ctx.chatCacheBySession).map(Number).sort((a, b) => a - b), [5, 6, 7, 8, 9, 10, 11, 12]);
  ctx.chatCachePut(5, { by_date: [], id: 5 }); // used again: it is now the newest
  ctx.chatCachePut(13, { by_date: [], id: 13 });
  assert.ok(ctx.chatCacheBySession[5], "a chat used again must stay");
  assert.equal(ctx.chatCacheBySession[6], undefined, "the one unused longest goes");
  assert.equal(Object.keys(ctx.chatCacheBySession).length, 8);
});

function fakeChat(ids, dayLabels = ["Today"]) {
  const box = {
    inserted: [],
    querySelectorAll(sel) {
      if (sel.includes(".msg")) return ids.map((n) => ({ id: "msg-" + n }));
      if (sel.includes(".day span")) return dayLabels.map((t) => ({ textContent: t }));
      return [];
    },
    querySelector: () => null,
    insertAdjacentHTML(pos, h) { this.inserted.push([pos, h]); },
  };
  return box;
}

function appendCtx(box, extra = {}) {
  const calls = [];
  const g = {
    $: () => box,
    esc: (s) => String(s),
    renderMsg: (m) => `<m${m.id}>`,
    hideThinking: () => calls.push("hideThinking"),
    applyCategory: () => {}, detectCategoryFromMsgs: () => "", currentMode: () => "",
    wireFollowups: () => {}, wireEngagementSignals: () => {}, renderMermaidIn: () => {},
    paintSendFailure: () => {}, scrollChatIfPinned: () => calls.push("scroll"),
    scrollChatBottomNow: () => {}, updateMsgScrollRail: () => {},
    document: { getElementById: () => null },
    chatFreshOpen: false, chatDomSess: 7, calls, ...extra,
  };
  const ctx = load(["renderedMsgIds", "appendChatTail"], g);
  return { ctx, calls };
}

const msg = (id, source = "ai") => ({ id, source, kind: "text" });
const payload = (...ms) => ({ by_date: [{ label: "Today", messages: ms }] });

test("only the new messages are added when the page already shows the same chat", () => {
  const box = fakeChat([1, 2, 3]);
  const { ctx, calls } = appendCtx(box);
  const ok = ctx.appendChatTail(payload(msg(1, "ai-chat"), msg(2), msg(3, "ai-chat"), msg(4), msg(5, "ai-chat")), 7);
  assert.equal(ok, true);
  assert.equal(box.inserted.length, 1);
  assert.equal(box.inserted[0][1], "<m4><m5>", "exactly the two new messages, nothing re-sent");
  assert.ok(calls.includes("hideThinking"), "a new reply clears the thinking line");
});

test("a longer fetch that starts earlier than the page does not re-add old messages", () => {
  const box = fakeChat([10, 11, 12]);
  const { ctx } = appendCtx(box);
  const ok = ctx.appendChatTail(payload(msg(7), msg(8), msg(9), msg(10), msg(11), msg(12), msg(13)), 7);
  assert.equal(ok, true);
  assert.equal(box.inserted[0][1], "<m13>");
});

test("a new day gets its heading", () => {
  const box = fakeChat([1], ["Yesterday"]);
  const { ctx } = appendCtx(box);
  const p = { by_date: [{ label: "Yesterday", messages: [msg(1)] }, { label: "Today", messages: [msg(2)] }] };
  assert.equal(ctx.appendChatTail(p, 7), true);
  assert.equal(box.inserted[0][1], '<div class="day"><span>Today</span></div><m2>');
});

test("nothing new means nothing is touched", () => {
  const box = fakeChat([1, 2]);
  const { ctx } = appendCtx(box);
  assert.equal(ctx.appendChatTail(payload(msg(1), msg(2)), 7), true);
  assert.equal(box.inserted.length, 0);
});

test("a deleted message, another chat or an empty page means a full rebuild", () => {
  // message 2 was deleted on the server
  let { ctx } = appendCtx(fakeChat([1, 2, 3]));
  assert.equal(ctx.appendChatTail(payload(msg(1), msg(3), msg(4)), 7), false);
  // the page shows a different chat
  ({ ctx } = appendCtx(fakeChat([1, 2, 3], ["Today"]), { chatDomSess: 8 }));
  assert.equal(ctx.appendChatTail(payload(msg(1), msg(2), msg(3), msg(4)), 7), false);
  // nothing on the page yet
  ({ ctx } = appendCtx(fakeChat([])));
  assert.equal(ctx.appendChatTail(payload(msg(1)), 7), false);
  // the server has nothing
  ({ ctx } = appendCtx(fakeChat([1])));
  assert.equal(ctx.appendChatTail({ by_date: [] }, 7), false);
  // the page has messages the server no longer sends in the window (all replaced)
  ({ ctx } = appendCtx(fakeChat([1, 2])));
  assert.equal(ctx.appendChatTail(payload(msg(5), msg(6)), 7), false);
});

test("polling is quick while active, slower when quiet, slowest when hidden", () => {
  const now = Date.now();
  const mk = (hidden, quietMs) => load(["syncDelay"], { document: { hidden }, Date: { now: () => now }, syncLastAct: now - quietMs });
  assert.equal(mk(false, 1000).syncDelay(), 1000);
  assert.equal(mk(false, 20000).syncDelay(), 2000);
  assert.equal(mk(false, 40000).syncDelay(), 4000);
  assert.equal(mk(true, 0).syncDelay(), 15000);
  assert.ok(mk(false, 10 * 60000).syncDelay() <= 5000, "a message from another device must show within a few seconds");
});

test("the 'still answering' note shows only for a question with no reply and no live stream here", () => {
  const box = {
    last: { dataset: { ai: "0" } }, note: null, added: 0,
    querySelectorAll() { return [this.last]; },
    insertAdjacentHTML() { this.added++; this.note = { remove: () => { this.note = null; } }; },
  };
  const g = {
    $: () => box, currentSession: 5, aiPending: false, streamSessionGen: 1, sessionGen: 1,
    scrollChatIfPinned: () => {},
    document: { getElementById: () => box.note },
  };
  const ctx = load(["syncGenNote"], g);
  ctx.syncGenNote(5, true);
  assert.equal(box.added, 1, "bare question while the server is answering: show it");
  ctx.syncGenNote(5, true);
  assert.equal(box.added, 1, "not twice");
  ctx.syncGenNote(5, false);
  assert.equal(box.note, null, "gone once the server stops, even if no reply came");
  box.last.dataset.ai = "1";
  ctx.syncGenNote(5, true);
  assert.equal(box.added, 1, "a reply is already there");
  box.last.dataset.ai = "0";
  g.aiPending = true;
  ctx.syncGenNote(5, true);
  assert.equal(box.added, 1, "this tab shows the live stream itself");
  g.aiPending = false;
  ctx.syncGenNote(6, true);
  assert.equal(box.added, 1, "another chat's note is not drawn here");
});
