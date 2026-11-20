/**
 * Chat seams in index.html: the edit chip, the failure record and Try again, and the
 * staged-file note. Same method as chat_shell.test.mjs: pull top-level functions out of
 * the page and run them against stand-in globals.   node --test tests/chat_seams.test.mjs
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

function page(names, extra = {}) {
  const box = { value: "", dispatchEvent() {} };
  const g = {
    box, toasts: [], sentCalls: [], clearedDrafts: [], currentSession: 7,
    $: (id) => (id === "input" ? box : null),
    document: { getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] },
    toast(t) { g.toasts.push(t); },
    autoGrowInput() {}, updateSendVisibility() {},
    clearComposerDraft(k) { g.clearedDrafts.push(k); },
    Event: class {},
    ...extra,
  };
  const ctx = vm.createContext(g);
  const src = "let editingMsgId=0,editingSession=0,editCarryIds=[];let retryIds=[];let _retrySend=false;let sendFailure=null;\n"
    + names.map(grab).join("\n");
  vm.runInContext(src, ctx);
  return ctx;
}

test("leaving a chat mid-edit drops the edit and its saved draft, so Enter cannot ask it twice", () => {
  const ctx = page(["clearEdit", "syncEditChip"], { purgeStaleQueue() {} });
  vm.runInContext("editingMsgId=41;editingSession=7;", ctx);
  ctx.currentSession = 9;                       // the person opened another chat
  ctx.syncEditChip();
  assert.deepEqual(ctx.clearedDrafts, ["s:7"], "the draft saved from the edit box must be cleared");
  assert.equal(vm.runInContext("editingMsgId", ctx), 0);
});

test("an edit in the open chat is left alone", () => {
  const ctx = page(["clearEdit", "syncEditChip"], { purgeStaleQueue() {} });
  vm.runInContext("editingMsgId=41;editingSession=7;", ctx);
  ctx.syncEditChip();
  assert.deepEqual(ctx.clearedDrafts, []);
  assert.equal(vm.runInContext("editingMsgId", ctx), 41);
});

test("the failure record keeps the files and the edited question's id", () => {
  const ctx = page(["noteSendFailure"]);
  ctx.noteSendFailure("q", "boom", { attachment_ids: [3, 4], replace_msg_id: 12 });
  assert.deepEqual(JSON.parse(vm.runInContext("JSON.stringify(sendFailure)", ctx)),
    { sid: 0, text: "q", msg: "boom", ids: [3, 4], replace: 12 });
  ctx.noteSendFailure("plain", "boom");
  assert.deepEqual(JSON.parse(vm.runInContext("JSON.stringify(sendFailure.ids)", ctx)), []);
});

test("Try again sends the question with the files it had", async () => {
  const ctx = page(["retryFailedSend"], {
    api: async () => ({ ok: true }), msgById: {},
    send(t) { ctx.seen = vm.runInContext("JSON.stringify(retryIds)", ctx); ctx.sentText = t; },
  });
  vm.runInContext("sendFailure={sid:7,text:'FAILQ',msg:'x',ids:[5,6],replace:0};", ctx);
  await ctx.retryFailedSend();
  assert.deepEqual(JSON.parse(ctx.seen), [5, 6]);
  assert.equal(ctx.sentText, "FAILQ");   // sent as its own text; the box is not used for it
  assert.equal(ctx.box.value, "");
});

test("Try again on a failed edit asks the same edit again and keeps the old question", async () => {
  const calls = [];
  const ctx = page(["retryFailedSend", "resumeEdit", "showEditChip"], {
    api: async (...a) => { calls.push(a); return { ok: true }; }, msgById: {},
    send(t) { ctx.sentText = t; ctx.seen = vm.runInContext("JSON.stringify([editingMsgId,editingSession,editCarryIds])", ctx); },
  });
  vm.runInContext("sendFailure={sid:7,text:'edited',msg:'x',ids:[8],replace:41};", ctx);
  await ctx.retryFailedSend();
  assert.deepEqual(JSON.parse(ctx.seen), [41, 7, [8]]);
  assert.equal(ctx.sentText, "edited");
  assert.deepEqual(calls, [], "the old question must not be deleted");
});

test("an edit that did not go through comes back in the box, in the same chat only", () => {
  const ctx = page(["resumeEdit", "showEditChip"]);
  ctx.resumeEdit(41, 9, "edited", [8]);          // the person is now in chat 7, not 9
  assert.equal(vm.runInContext("editingMsgId", ctx), 0);
  ctx.resumeEdit(41, 7, "edited", [8]);
  assert.equal(vm.runInContext("editingMsgId", ctx), 41);
  assert.equal(ctx.box.value, "edited");
  assert.deepEqual(JSON.parse(vm.runInContext("JSON.stringify(editCarryIds)", ctx)), [8]);
});

test("Edit and Try again stay out of the way while the chat is still answering", () => {
  for (const fn of ["editLastUser", "regenerateLast"]) {
    const ctx = page([fn], {
      aiPending: false, sendInFlight: false,
      document: { getElementById: (id) => (id === "gen-note" ? {} : null), querySelector: () => null },
      lastTurnIds() { throw new Error("must not get this far"); },
    });
    ctx[fn]();
    assert.deepEqual(ctx.toasts, ["AirGPT is still answering in this chat. Wait for it or press Stop."], fn);
  }
});

test("a staged file with a reply running says what happens to the text", async () => {
  const ctx = page(["_sendInner"], {
    aiMode: true, aiPending: false, sendInFlight: true, sideView: "chats", stagedFiles: [{ name: "a.txt" }],
    contextIds: [], messageQueue: [], sessionGen: 1, window: {},
    peelSkillSlash: () => null, handleSlashCommand: () => false, dispatchAtAgent: async () => false,
  });
  ctx.box.value = "QUEUED-WITH-FILE";
  await ctx._sendInner();
  assert.deepEqual(ctx.toasts, ["Your text stays in the box. Send it after this reply, or remove the file to queue it."]);
  assert.equal(ctx.box.value, "QUEUED-WITH-FILE");
  assert.equal(ctx.messageQueue.length, 0);
});

// ---- last round: queued lines, Stop on Regenerate, the edit chip across reload and tabs ----

function sendPage(extra = {}) {
  const calls = [];
  const ctx = page(["_sendInner"], {
    aiMode: true, aiPending: false, sendInFlight: false, sideView: "chats", stagedFiles: [],
    contextIds: [], messageQueue: [], sessionGen: 1, window: {}, replyContext: null, info: { online: true },
    peelSkillSlash: () => null, handleSlashCommand: () => false, dispatchAtAgent: async () => false,
    trackPref() {}, ensureDeviceName() {}, applyPlaceholder() {}, ensureChatSession: async () => 7,
    QUESTIONS_OF_THE_DAY: [], settleQueue() {}, resumeEdit() {}, currentMode: () => "general", autoGrowInput() {},
    clearEdit() { vm.runInContext("editingMsgId=0;editingSession=0;editCarryIds=[];", ctx); },
    async sendStream(text, extra) { calls.push({ text, extra }); return { ok: true }; },
    ...extra,
  });
  ctx.calls = calls;
  return ctx;
}

test("a queued line never inherits an edit: no replace id, no edit files, the edit stays armed", async () => {
  const ctx = sendPage();
  vm.runInContext("editingMsgId=41;editingSession=7;editCarryIds=[8];retryIds=[9];", ctx);
  await ctx._sendInner("QUEUED line");
  assert.equal(ctx.calls.length, 1);
  assert.equal(ctx.calls[0].extra.replace_msg_id, undefined, "a queued line is a new question");
  assert.equal(ctx.calls[0].extra.attachment_ids, undefined, "no files of the edit or a retry ride along");
  assert.equal(vm.runInContext("editingMsgId", ctx), 41, "the resumed edit is still there for the person");
});

test("a typed send still carries its edit (the normal Edit keeps working)", async () => {
  const ctx = sendPage();
  vm.runInContext("editingMsgId=41;editingSession=7;editCarryIds=[8];", ctx);
  ctx.box.value = "EDITED";
  await ctx._sendInner();
  assert.equal(ctx.calls[0].extra.replace_msg_id, 41);
  assert.deepEqual([...ctx.calls[0].extra.attachment_ids], [8]);
  assert.equal(vm.runInContext("editingMsgId", ctx), 0);
});

test("Stop on Regenerate before any text shows the old answer again", async () => {
  for (const [res, shown] of [[{ ok: true, stopped: true, saved: false }, true], [{ ok: false }, true], [{ ok: true, saved: true }, false]]) {
    const old = { style: { display: "none" } };
    const ctx = page(["regenerateLast"], {
      aiPending: false, sendInFlight: false, settleQueue() {},
      lastTurnIds: () => ({ q: 5, text: "Q", ai: 6 }),
      document: { getElementById: (id) => (id === "msg-6" ? old : null), querySelector: () => null },
      sendStream: async () => res,
    });
    await ctx.regenerateLast();
    assert.equal(old.style.display, shown ? "" : "none", JSON.stringify(res));
  }
});

test("the text of an Edit is never stored as a draft (it would come back without its chip)", () => {
  const writes = [];
  const ctx = page(["saveComposerDraft"], {
    clearTimeout, setTimeout, composerDraftByKey: {}, _draftTimers: {}, draftKey: () => "s:7",
    _draftWrite: (k, v) => writes.push([k, v]),
  });
  ctx.box.value = "edit text";
  vm.runInContext("editingMsgId=41;editingSession=7;", ctx);
  ctx.saveComposerDraft();
  assert.deepEqual(writes, [["s:7", ""]]);
  assert.deepEqual(Object.keys(ctx._draftTimers), []);
  vm.runInContext("editingMsgId=0;editingSession=0;", ctx);
  ctx.saveComposerDraft();
  assert.deepEqual(Object.keys(ctx._draftTimers), ["s:7"], "a normal draft is still saved");
  clearTimeout(ctx._draftTimers["s:7"]);
});

test("when the chat's last question is no longer the edited one, the chip goes and the text stays", () => {
  const saved = [];
  const ctx = page(["clearEdit", "syncEditChip"], {
    purgeStaleQueue() {}, saveComposerDraft() { saved.push(ctx.box.value); },
    lastTurnIds: () => ({ q: 55, text: "newer", ai: 56 }),
    document: { getElementById: () => null, querySelector: () => null, querySelectorAll: () => [{}] },
  });
  ctx.box.value = "B EDIT TEXT";
  vm.runInContext("editingMsgId=41;editingSession=7;", ctx);
  ctx.syncEditChip();
  assert.equal(vm.runInContext("editingMsgId", ctx), 0);
  assert.equal(ctx.box.value, "B EDIT TEXT");
  assert.deepEqual(saved, ["B EDIT TEXT"]);
});

// ---- final round: @Agent line, Try again keeps the box ----

function agentPage(agents, extra = {}) {
  const ran = [];
  const ctx = page(["dispatchAtAgent"], {
    api: async () => ({ json: async () => ({ agents }) }),
    ensureChatSession: async () => 7,
    runCortexAgentWithPrompt: (id, prompt, line) => ran.push([id, prompt, line]),
    ...extra,
  });
  ctx.ran = ran;
  return ctx;
}

test("'@property versus @classmethod ...' is a question, not an agent command", async () => {
  const ctx = agentPage([{ id: 1, name: "RAG" }, { id: 2, name: "Scout" }]);
  assert.equal(await ctx.dispatchAtAgent("@property versus @classmethod in Python, which for a factory?"), false);
  assert.deepEqual(ctx.ran, []);
  assert.deepEqual(ctx.toasts, []);
});

test("an exact agent name (any case) still runs that agent with the rest of the line and the whole line", async () => {
  const ctx = agentPage([{ id: 1, name: "RAG" }, { id: 2, name: "Scout" }]);
  assert.equal(await ctx.dispatchAtAgent("@scout find the thing"), true);
  assert.deepEqual(ctx.ran, [[2, "find the thing", "@scout find the thing"]]);
});

test("Try again sends the failed text on its own and leaves the waiting lines in the box", async () => {
  const sent = [];
  const ctx = page(["retryFailedSend"], { send: (t) => sent.push(t), api: async () => ({ ok: true }), msgById: {} });
  vm.runInContext("sendFailure={text:'second question',ids:[3]};", ctx);
  ctx.box.value = "WAITING LINE ONE";
  await ctx.retryFailedSend();
  assert.deepEqual(sent, ["second question"]);
  assert.equal(ctx.box.value, "WAITING LINE ONE");
  assert.equal(vm.runInContext("_retrySend", ctx), true);
  assert.equal(vm.runInContext("JSON.stringify(retryIds)", ctx), "[3]");
});

test("Try again on a failed edit keeps the waiting lines in the box too", async () => {
  const sent = [];
  const ctx = page(["retryFailedSend"], { send: (t) => sent.push(t), resumeEdit() {} });
  vm.runInContext("sendFailure={text:'edited question',replace:41,sid:7,ids:[]};", ctx);
  ctx.box.value = "WAITING LINE\n\nmore";
  await ctx.retryFailedSend();
  assert.deepEqual(sent, ["edited question"]);
  assert.equal(ctx.box.value, "WAITING LINE\n\nmore");
});
