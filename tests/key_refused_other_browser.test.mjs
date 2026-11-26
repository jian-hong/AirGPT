/**
 * A refused key reads as refused in a browser that never saw the refusal (the phone,
 * a cleared browser). The server writes the reason into the error text; a fresh,
 * empty localStorage must be enough.  node --test tests/key_refused_other_browser.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
function grab(name) {
  const m = new RegExp("^(async )?function " + name + "\\(", "m").exec(html);
  assert.ok(m, name + " missing");
  let depth = 0;
  for (let j = html.indexOf("{", m.index); j < html.length; j++) {
    if (html[j] === "{") depth++;
    else if (html[j] === "}" && --depth === 0) return html.slice(m.index, j + 1);
  }
  throw new Error("unbalanced");
}
function freshBrowser(isLocal = false) {
  const store = {};
  const ctx = vm.createContext({ isLocalHost: () => isLocal, localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; } } });
  vm.runInContext(grab("sendFailureCopy"), ctx);
  return ctx.sendFailureCopy;
}

test("a fresh browser reads 'key refused' from the server text", () => {
  const c = freshBrowser(false)("Model failed - tried Groq: No text LLM available (groq-oss-120b(key refused) -> groq-qwen3.6-27b(key refused) -> Google(no key))");
  assert.equal(c.title, "Your Groq key was refused");
  assert.match(c.body, /owner/);
});

test("a rate limit reads busy in a fresh browser, never refused", () => {
  const c = freshBrowser(true)("No text LLM available (groq-oss-120b(cooldown, rate limited) -> Google(no key))");
  assert.equal(c.title, "Groq is busy");
});

test("a refusal after a busy provider is still named", () => {
  const c = freshBrowser(true)("No text LLM available (openrouter-llama(cooldown, rate limited) -> groq-70b(key refused) -> Google(no key))");
  assert.equal(c.title, "Your Groq key was refused");
});

test("an unreachable provider is not called busy", () => {
  const c = freshBrowser(true)("No text LLM available (groq-70b(cooldown, unreachable))");
  assert.match(c.title, /could not be reached/);
});
