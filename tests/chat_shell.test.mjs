/**
 * Behaviour tests for small pieces of the main chat shell in index.html.
 *
 * The page is one big inline script, so each test pulls one top-level function out of
 * the file and runs it against stand-in globals. Run with:
 *   node --test tests/chat_shell.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

/** Source of one top-level function, found by name and cut at its closing brace. */
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

function load(names, globals) {
  const ctx = vm.createContext(globals);
  vm.runInContext(names.map(grab).join("\n"), ctx);
  return ctx;
}

function fakeImg() {
  const img = { style: {}, dataset: {}, srcSets: 0, _src: "" };
  Object.defineProperty(img, "src", { get() { return this._src; }, set(v) { this._src = v; this.srcSets++; } });
  return img;
}

test("setQR leaves the picture alone while the link is unchanged", () => {
  const ctx = load(["setQR"], { qrSrc: (u) => "/api/qr.png?data=" + u, toast() {}, Date });
  const img = fakeImg();
  ctx.setQR(img, "http://a/b");
  ctx.setQR(img, "http://a/b");
  ctx.setQR(img, "http://a/b");
  assert.equal(img.srcSets, 1, "the sync poll must not reload the QR image every time");
  ctx.setQR(img, "http://a/c");
  assert.equal(img.srcSets, 2, "a new link must load a new picture");
});

test("setQR shows the picture again after the link was cleared", () => {
  const ctx = load(["setQR"], { qrSrc: (u) => "/api/qr.png?data=" + u, toast() {}, Date });
  const img = fakeImg();
  ctx.setQR(img, "http://a/b");
  ctx.setQR(img, "—");
  assert.equal(img.style.display, "none");
  ctx.setQR(img, "http://a/b");
  assert.equal(img.style.display, "block");
  assert.equal(img.srcSets, 2);
});

test("setQR tells the user in words when the QR cannot be made", () => {
  const made = [];
  const document = {
    createElement() { const n = { classList: { contains: () => true }, hidden: true, textContent: "" }; made.push(n); return n; },
  };
  const ctx = load(["setQR"], { qrSrc: (u) => "/x?" + u, toast() {}, Date, document });
  const img = fakeImg();
  img.after = (n) => { img.nextElementSibling = n; };
  ctx.setQR(img, "http://a/b");
  img.onerror();
  assert.equal(img.style.display, "none", "no broken-image icon");
  assert.equal(made.length, 1);
  assert.match(made[0].textContent, /could not be drawn/i);
  assert.equal(made[0].hidden, false);
});

function bodyWith(...classes) {
  const set = new Set(classes);
  return { classList: { add: (c) => set.add(c), remove: (c) => set.delete(c), contains: (c) => set.has(c) }, set };
}

test("a chat becoming current ends the home state and refreshes the header", () => {
  for (const already of [false, true]) {
    const body = bodyWith("claude-home");
    let synced = 0;
    const ctx = load(["adoptSessionId"], {
      document: { body },
      currentSession: already ? 7 : 0,
      aiPending: false,
      streamSessionGen: 0,
      sessionGen: 0,
      localStorage: { setItem() {} },
      syncChatTitleBar: () => { synced++; },
      parseInt,
    });
    ctx.adoptSessionId(7);
    assert.equal(body.set.has("claude-home"), false, "claude-home must not outlive the first chat (already=" + already + ")");
    assert.ok(synced >= 1, "the chat header must be re-evaluated");
  }
});

test("search project filter also applies to message hits", async () => {
  let painted = null;
  const ctx = load(["runSearch"], {
    _searchProjectFilter: "engineering",
    _searchSort: "relevance",
    _searchResultCache: new Map(),
    cachedSessions: [
      { id: 1, category: "general" },
      { id: 2, category: "engineering" },
    ],
    $: () => ({ value: "plan", innerHTML: "" }),
    api: async () => ({
      json: async () => ({
        sessions: [],
        messages: [
          { id: 10, session_id: 1, text: "plan A" },
          { id: 11, session_id: 2, text: "plan B" },
        ],
      }),
    }),
    renderSearchHits: (hits) => { painted = hits; },
  });
  await ctx.runSearch("plan", [], "k");
  assert.deepEqual(Array.from(painted.map((h) => h.id)), [11]);
});

test("the search chips come from the same project list as the rest of the app", () => {
  const made = [];
  const box = {
    appended: [],
    querySelectorAll: () => ({ forEach() {} }),
    appendChild(b) { this.appended.push(b); },
  };
  const ctx = load(["buildSearchChips"], {
    MODES: ["general", "engineering", "finance", "ml"],
    MODE_LABELS: { general: "General", engineering: "Engineering", finance: "Finance", ml: "Machine Learning" },
    _searchProjectFilter: "all",
    $: () => box,
    document: {
      createElement: () => {
        const b = { dataset: {}, classList: { toggle() {} }, addEventListener() {} };
        made.push(b);
        return b;
      },
    },
  });
  ctx.buildSearchChips();
  assert.deepEqual(Array.from(box.appended.map((b) => b.dataset.proj)), ["general", "engineering", "finance", "ml"]);
  assert.equal(box.appended[3].textContent, "Machine Learning");
});

test("the duplicate controls and dead rules are gone", () => {
  assert.equal((html.match(/^function showLogin\(/gm) || []).length, 1, "showLogin declared once");
  for (const gone of ["navAllAgents", 'data-wired="0"']) {
    assert.ok(!html.includes(gone), gone + " should be removed");
  }
  assert.ok(!/onclick="event\.stopPropagation\(\);addProject\(\)">\+ Project/.test(html), "second New project button");
  assert.ok(!/\.banner-x\{[^}]*color:#fff/.test(html), "banner close button must follow the theme colour");
});

test("the sidebar can be opened from the top bar and from the edge tab", () => {
  // Not a duplicate pair: the sidebar starts closed up to 1400px wide, so the top-bar
  // button is the one people find; the edge tab is the only route in short windows,
  // where the top bar slides away.
  assert.ok(/id="sideToggleTop"[^>]*onclick="toggleSideCollapsed\(\)"/.test(html), "top-bar sidebar button");
  assert.ok(html.includes('id="sideCollapseBtn"'), "edge tab");
  assert.ok(/@media\(max-width:760px\)\{[^@]*\.side-toggle-top\{display:none\}/.test(html), "phones use the drawer button instead");
});

test("Connectors opens the panel it names", () => {
  assert.ok(!/Settings → Integrations/.test(html));
  assert.ok(/Tools & MCPs'\);\s*openSettings\('tools'\)/.test(html));
});

test("the chat header is re-checked whenever the side view changes", () => {
  assert.ok(grab("updateSideNav").includes("syncChatTitleBar"), "updateSideNav must hide the chat header on Cortex and Projects");
});
