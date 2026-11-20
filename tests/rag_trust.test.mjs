/**
 * Page text for the RAG answers-you-can-trust lane: chat card previews, skip reasons and
 * the same-name note in the upload report. Run with: node --test tests/rag_trust.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

function grab(name) {
  const m = new RegExp("^(async )?function " + name + "\\(", "m").exec(html);
  assert.ok(m, "function " + name + " not found in index.html");
  const i = html.indexOf("{", m.index);
  let depth = 0;
  for (let j = i; j < html.length; j++) {
    if (html[j] === "{") depth++;
    else if (html[j] === "}" && --depth === 0) return html.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces in " + name);
}
function page(names) {
  const ctx = vm.createContext({ ragState: {}, Number, Set, Array, String, Math });
  vm.runInContext(names.map(grab).join("\n"), ctx);
  return ctx;
}

test("chat card preview is plain words", () => {
  const { ragPlainPreview } = page(["ragPlainPreview"]);
  const out = ragPlainPreview("## Answer\n\nEmployees get **18 days** of annual leave [1]. See [the policy](http://x/y) and `code` [2, 3].");
  assert.equal(out, "Answer Employees get 18 days of annual leave. See the policy and code.");
  assert.ok(!/[#*`\[\]]/.test(out));
});

test("a bracket that is not a citation stays", () => {
  const { ragPlainPreview } = page(["ragPlainPreview"]);
  assert.equal(ragPlainPreview("Task [x] done"), "Task [x] done");
});

test("skip reasons: damaged and empty are different words", () => {
  const { ragSkipReason } = page(["ragSkipReason"]);
  const bad = ragSkipReason("fake.docx", "could not be read (damaged, or not really a docx file)");
  const empty = ragSkipReason("blank.txt", "empty (no text in the file)");
  assert.match(bad, /could not be read/);
  assert.match(empty, /is empty/);
  assert.notEqual(bad, empty);
  assert.match(ragSkipReason("blob.bin", "Looks like a binary file, not text"), /not text/);
});

test("upload report says a same-name file was kept beside the old one", () => {
  const { ragUploadSummary, ragUploadReportHtml } = page(["ragSkipReason", "ragUploadSummary", "esc", "ragUploadReportHtml"].filter((n) => new RegExp("function " + n + "\\(").test(html)));
  const rep = ragUploadSummary(1, { sources: 1, chunks: 3, skipped: [], renamed: [{ from: "notes.md", to: "notes_2.md" }] }, [], 1);
  assert.equal(rep.notes.length, 1);
  assert.match(rep.notes[0], /notes\.md/);
  assert.match(rep.notes[0], /notes_2\.md/);
});

test("a star or underscore that is arithmetic or a name stays", () => {
  const { ragPlainPreview } = page(["ragPlainPreview"]);
  assert.equal(ragPlainPreview("Total is 5*3=15 and 2 * 4 = 8"), "Total is 5*3=15 and 2 * 4 = 8");
  assert.equal(ragPlainPreview("Use snake_case_name here"), "Use snake_case_name here");
  assert.equal(ragPlainPreview("It is **bold**, *soft* and ~~gone~~."), "It is bold, soft and gone.");
});
