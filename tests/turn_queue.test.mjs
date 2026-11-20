/**
 * The waiting-message queue, the unsent-text restore and the reply label in index.html.
 * Same method as chat_shell.test.mjs: pull each top-level function out of the page and
 * run it against stand-in globals.   node --test tests/turn_queue.test.mjs
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

function page(extra = {}) {
  const box = { value: "" };
  const toasts = [];
  const sent = [];
  const g = {
    messageQueue: [], sessionGen: 1, aiPending: false, sendInFlight: false,
    toasts, sent, box,
    $: (id) => (id === "input" ? box : null),
    toast: (t) => toasts.push(t),
    updateQueueHint() {}, autoGrowInput() {}, updateSendVisibility() {},
    send: (t) => { sent.push(t); },
    esc: (s) => String(s),
    ...extra,
  };
  const ctx = vm.createContext(g);
  vm.runInContext(
    ["purgeStaleQueue", "drainMessageQueue", "settleQueue", "restoreUnsentText", "aiWho"].map(grab).join("\n"),
    ctx,
  );
  return ctx;
}

test("a waiting message is sent when the reply is over, in the order typed", () => {
  const p = page();
  p.messageQueue = [{ text: "one", gen: 1 }, { text: "two", gen: 1 }];
  p.drainMessageQueue();
  assert.deepEqual(p.sent, ["one"]);
  assert.deepEqual(p.messageQueue.map((q) => q.text), ["two"]);
});

test("nothing is sent while a reply is still coming", () => {
  const p = page();
  p.messageQueue = [{ text: "one", gen: 1 }];
  p.aiPending = true;
  p.drainMessageQueue();
  assert.deepEqual(p.sent, []);
  p.aiPending = false; p.sendInFlight = true;
  p.drainMessageQueue();
  assert.deepEqual(p.sent, []);
});

test("a waiting message never lands in another chat", () => {
  const p = page();
  p.messageQueue = [{ text: "for the old chat", gen: 1 }];
  p.sessionGen = 2;   // the person opened another chat
  p.drainMessageQueue();
  assert.deepEqual(p.sent, []);
  assert.equal(p.messageQueue.length, 0);
  assert.match(p.toasts.join(" "), /changed chats/i, "the person is told it was not sent");
});

test("when the turn failed, waiting messages go back in the box instead of being sent", () => {
  const p = page();
  p.messageQueue = [{ text: "first waiting", gen: 1 }, { text: "second waiting", gen: 1 }];
  p.box.value = "half typed";
  p.settleQueue(false);
  assert.equal(p.messageQueue.length, 0);
  assert.deepEqual(p.sent, []);
  assert.equal(p.box.value, "first waiting\n\nsecond waiting\n\nhalf typed");
  assert.match(p.toasts.join(" "), /not sent/i);
});

test("when the turn worked, settling sends the next waiting message", async () => {
  const p = page({ setTimeout: (f) => f() });
  p.messageQueue = [{ text: "next", gen: 1 }];
  p.settleQueue(true);
  assert.deepEqual(p.sent, ["next"]);
});

test("a refused message comes back ahead of anything typed since", () => {
  const p = page();
  p.box.value = "typed after";
  p.restoreUnsentText("the refused one");
  assert.equal(p.box.value, "the refused one\n\ntyped after");
  p.box.value = "";
  p.restoreUnsentText("only this");
  assert.equal(p.box.value, "only this");
});

test("a reply is labelled with what wrote it, not always Netie Cortex", () => {
  const p = page();
  assert.equal(p.aiWho({ ai_model: "cortex-agent" }), "Netie Cortex");
  assert.equal(p.aiWho({ ai_model: "ollama" }), "Your local model");
  assert.equal(p.aiWho({ ai_model: "dual:groq-llama+deepseek-reasoner" }), "deepseek-reasoner");
  assert.equal(p.aiWho({ ai_model: "" }), "Assistant");
  assert.equal(p.aiWho({}), "Assistant");
});
