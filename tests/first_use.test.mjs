/**
 * First-use copy in index.html: what a failed reply says when a key was refused or a
 * provider is cooling down. Run with:  node --test tests/first_use.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
function grab(name) {
  const m = new RegExp("^(async )?function " + name + "\\(", "m").exec(html);
  assert.ok(m, "function " + name + " not found in index.html");
  let depth = 0;
  for (let j = html.indexOf("{", m.index); j < html.length; j++) {
    if (html[j] === "{") depth++;
    else if (html[j] === "}" && --depth === 0) return html.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces in " + name);
}
function copyFn(isLocal) {
  const store = {};
  const ctx = vm.createContext({ isLocalHost: () => isLocal, localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; } } });
  vm.runInContext(grab("sendFailureCopy"), ctx);
  return ctx.sendFailureCopy;
}

test("a refused key and a cooling-down provider are told apart from no key", () => {
  const host = copyFn(true);
  const refused = host(
    "Model failed - tried Groq/Google: No text LLM available (ollama(down) -> OpenVault(not running) -> groq-oss-120b(HTTP Error 401: Unauthorized) -> groq-70b(HTTP Error 401: Unauthorized) -> Google(no key))");
  assert.equal(refused.title, "Your Groq key was refused");
  assert.match(refused.body, /Settings > API/);
  assert.equal(refused.key, true);
  // the same key, asked again while the server only says "cooldown", is still a refused key
  assert.equal(host("No text LLM available (groq-oss-120b(cooldown) -> groq-70b(cooldown) -> Google(no key))").title, "Your Groq key was refused");
  const busy = copyFn(true)("No text LLM available (ollama(down) -> groq-70b(HTTP Error 429: Too Many Requests) -> Google(no key))");
  assert.equal(busy.title, "Groq is busy");
  assert.match(busy.body, /Wait/);
  assert.ok(!busy.key);
  const guest = copyFn(false)("No text LLM available (groq-70b(HTTP Error 403: Forbidden))");
  assert.ok(!guest.key && /owner/.test(guest.body), "a guest is told to ask the owner");
});

test("no key at all still reads as no model", () => {
  const c = copyFn(true)("No text LLM available (ollama(down) -> Groq(no key) -> Google(no key))");
  assert.equal(c.title, "No AI model is ready");
  assert.equal(c.key, true);
});
