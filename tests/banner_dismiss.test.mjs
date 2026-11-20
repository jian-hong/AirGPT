/**
 * The plan banner's close button: it closes, the dismissal is remembered, and it still closes
 * (for this visit) when the browser will not store anything.   node --test tests/banner_dismiss.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
function grab(re) {
  const m = re.exec(html);
  assert.ok(m, "not found: " + re);
  let depth = 0;
  for (let j = html.indexOf("{", m.index); j < html.length; j++) {
    if (html[j] === "{") depth++;
    else if (html[j] === "}" && --depth === 0) return html.slice(m.index, j + 1);
  }
  throw new Error("unbalanced");
}
function page(storage) {
  const el = { classList: new Set(), cl: null };
  el.classList = { s: new Set(), add(c) { this.s.add(c); }, remove(c) { this.s.delete(c); }, contains(c) { return this.s.has(c); } };
  const ctx = vm.createContext({ localStorage: storage, $: () => el, setTimeout: (f) => f() });
  vm.runInContext("const _bannerGone={};" + grab(/^function dismissBanner\(/m) + grab(/^function bannerAllowed\(/m), ctx);
  return { ctx, el };
}

test("closing the banner hides it and the choice is remembered", () => {
  const store = {};
  const { ctx, el } = page({ getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; } });
  assert.equal(ctx.bannerAllowed("pay"), true);
  ctx.dismissBanner("pay");
  assert.ok(el.classList.contains("dismissed"));
  assert.equal(store.banner_dismiss_pay, "1");
  const again = page({ getItem: (k) => store[k] ?? null, setItem() {} });   // a reload
  assert.equal(again.ctx.bannerAllowed("pay"), false);
});

test("closing still works when the browser refuses storage", () => {
  const boom = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
  const { ctx, el } = page(boom);
  assert.equal(ctx.bannerAllowed("pay"), true);
  ctx.dismissBanner("pay");
  assert.ok(el.classList.contains("dismissed"));
  assert.equal(ctx.bannerAllowed("pay"), false, "stays closed for this visit");
});
