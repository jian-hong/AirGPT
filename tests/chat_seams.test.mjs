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
    document: { getElementById: () => null, querySelector: () => null },
    toast(t) { g.toasts.push(t); },
    autoGrowInput() {}, updateSendVisibility() {},
    clearComposerDraft(k) { g.clearedDrafts.push(k); },
    Event: class {},
    ...extra,
  };
  const ctx = vm.createContext(g);
  const src = "let editingMsgId=0,editingSession=0,editCarryIds=[];let retryIds=[];let sendFailure=null;\n"
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
    send() { ctx.seen = vm.runInContext("JSON.stringify(retryIds)", ctx); },
  });
  vm.runInContext("sendFailure={sid:7,text:'FAILQ',msg:'x',ids:[5,6],replace:0};", ctx);
  await ctx.retryFailedSend();
  assert.deepEqual(JSON.parse(ctx.seen), [5, 6]);
  assert.equal(ctx.box.value, "FAILQ");
});

test("Try again on a failed edit asks the same edit again and keeps the old question", async () => {
  const calls = [];
  const ctx = page(["retryFailedSend", "resumeEdit", "showEditChip"], {
    api: async (...a) => { calls.push(a); return { ok: true }; }, msgById: {},
    send() { ctx.seen = vm.runInContext("JSON.stringify([editingMsgId,editingSession,editCarryIds])", ctx); },
  });
  vm.runInContext("sendFailure={sid:7,text:'edited',msg:'x',ids:[8],replace:41};", ctx);
  await ctx.retryFailedSend();
  assert.deepEqual(JSON.parse(ctx.seen), [41, 7, [8]]);
  assert.equal(ctx.box.value, "edited");
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
