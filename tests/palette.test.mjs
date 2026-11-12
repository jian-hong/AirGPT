/**
 * Matcher tests for ui/palette.js. Run with:  node --test tests/palette.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { rank, scoreText } = require("../ui/palette.js");

const items = [
  { label: "New chat" },
  { label: "Search chats" },
  { label: "Open settings" },
  { label: "Switch theme: Light" },
  { label: "Go to Cortex workspace" },
  { label: "Effort: High" },
];
const labels = (r) => r.map((x) => x.label);

test("empty query keeps the given order and returns a copy", () => {
  const r = rank("", items);
  assert.deepEqual(labels(r), labels(items));
  assert.notEqual(r, items);
  assert.deepEqual(labels(rank("   ", items)), labels(items));
});

test("prefix beats word start beats scattered letters", () => {
  const a = scoreText("sea", "search chats");
  const b = scoreText("sea", "go to search");
  const c = scoreText("sea", "sxexa");
  assert.ok(a > b, "prefix should beat word start");
  assert.ok(b > c, "word start should beat scattered");
  assert.ok(c > 0);
  const r = rank("some", [{ label: "s_o_m_e" }, { label: "xx some thing" }, { label: "something else" }]);
  assert.deepEqual(labels(r), ["something else", "xx some thing", "s_o_m_e"]);
});

test("word start beats substring in the middle of a word", () => {
  const r = rank("set", [{ label: "Reset all" }, { label: "Open settings" }]);
  assert.equal(r[0].label, "Open settings");
  assert.equal(r.length, 2);
});

test("multi-word queries match word starts in order", () => {
  assert.equal(rank("sw th", items)[0].label, "Switch theme: Light");
  assert.equal(rank("go cor", items)[0].label, "Go to Cortex workspace");
});

test("scattered letters match, wrong order does not", () => {
  assert.equal(rank("nwc", items)[0].label, "New chat");
  assert.equal(rank("tcn", items).length, 0);
});

test("non matches are dropped and matching ignores case", () => {
  assert.equal(rank("zzz", items).length, 0);
  assert.equal(rank("NEW", items)[0].label, "New chat");
});

test("keywords match but rank below a label match", () => {
  const set = [{ label: "Open settings", keywords: "preferences" }, { label: "Preferences panel" }];
  const r = rank("pref", set);
  assert.equal(r[0].label, "Preferences panel");
  assert.equal(r[1].label, "Open settings");
});

test("ties keep input order", () => {
  const r = rank("chat", [{ label: "Chat one" }, { label: "Chat two" }]);
  assert.deepEqual(labels(r), ["Chat one", "Chat two"]);
});

test("handles odd input without throwing", () => {
  assert.equal(rank(null, [{ label: "a" }]).length, 1);
  assert.deepEqual(rank("a", null), []);
  assert.equal(rank("a", [{ label: null }]).length, 0);
});
