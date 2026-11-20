/**
 * Behaviour tests for the knowledge-space page (Build / RAG) in index.html: citations,
 * Markdown answers, spreadsheet provenance, honesty notes and the upload report.
 *
 * The page is one big inline script, so each test pulls the top-level functions it needs
 * out of the file and runs them against stand-in globals. Run with:
 *   node --test tests/rag_ui.test.mjs
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
function grabLine(re) {
  const m = re.exec(html);
  assert.ok(m, "line not found: " + re);
  return m[0];
}

const NAMES = [
  "esc", "ragFileName", "ragSrcIcon", "ragCiteList", "ragCiteFile", "ragCiteWhere", "ragCitesHtml",
  "ragSafeMoney", "ragLinkCiteChips", "ragMdHtml", "ragNum", "ragProvenanceLines", "ragProvenanceHtml",
  "ragNotesHtml", "ragSkipReason", "ragLooksBinary", "ragUploadSummary", "ragUploadReportHtml", "ragBytes",
];
function page(extra = {}) {
  const ctx = vm.createContext({ ragState: {}, Number, Set, Array, String, Math, Uint8Array, ...extra });
  vm.runInContext(
    "let _ragCiteSeq=0;\n" + grabLine(/^const RAG_KNOWN_BINARY=.*$/m) + "\n" + NAMES.map(grab).join("\n"),
    ctx
  );
  return ctx;
}

test("a dollar amount is not read as a formula, code and maths are left alone", () => {
  const c = page();
  const out = c.ragSafeMoney("It costs $5 and $10 in total, $36,048. Use `$5` here. Maths $2x+1$ stays.");
  assert.ok(out.startsWith("It costs &#36;5 and &#36;10 in total, &#36;36,048."));
  assert.ok(out.includes("`$5`"), "inline code must not change");
  assert.ok(out.includes("$2x+1$"), "a formula must not change");
  const fenced = c.ragSafeMoney("```\nprice = $5\n```\nthen $7");
  assert.ok(fenced.includes("price = $5") && fenced.includes("&#36;7"));
});

test("[n] chips only appear in plain text and only for numbers the answer really has", () => {
  const c = page();
  const src = '<p>Code is 1234 [1][5][8] and <code>a[1]</code> <a href="/x">[2]</a></p><pre>x[1]</pre>';
  const out = c.ragLinkCiteChips(src, "s7", ["1", "5"]);
  assert.equal((out.match(/class="rag-cite-chip"/g) || []).length, 2, out);
  assert.ok(out.includes('data-cite="1" data-scope="s7"') && out.includes('data-cite="5" data-scope="s7"'));
  assert.ok(out.includes("[8]") && !out.includes('data-cite="8"'), "a number with no source stays text");
  assert.ok(out.includes("<code>a[1]</code>") && out.includes('<a href="/x">[2]</a>') && out.includes("<pre>x[1]</pre>"));
  assert.ok(!/onclick/i.test(out), "no inline handler code");
  const web = c.ragLinkCiteChips("<p>see [W2] and [3]</p>", "s1", ["W2", "3"]);
  assert.equal((web.match(/rag-cite-chip/g) || []).length, 2);
});

test("every cited passage gets its own row, numbered as the model saw it, ids unique per answer", () => {
  const c = page();
  const mk = (n) => Array.from({ length: n }, (_, i) => ({ chunk_id: 100 + i, path: "door.txt", title: "door.txt", heading: "", excerpt: "e" + i }));
  const a = c.ragCitesHtml(mk(8), "s1");
  const b = c.ragCitesHtml([{ chunk_id: 5, path: "sal.csv", title: "sal.csv", heading: "", excerpt: "x" }], "s2");
  const idsA = [...a.matchAll(/id="(rag-cite-[^"]+)"/g)].map((m) => m[1]);
  const idsB = [...b.matchAll(/id="(rag-cite-[^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(idsA, [1, 2, 3, 4, 5, 6, 7, 8].map((n) => "rag-cite-s1-" + n), "same file, eight passages, eight rows");
  assert.deepEqual(idsB, ["rag-cite-s2-1"]);
  assert.equal(new Set([...idsA, ...idsB]).size, 9, "ids repeat across answers");
  assert.equal((a.match(/data-chunk=/g) || []).length, 8, "each row can open its own passage");
  assert.ok(a.includes("8 passages from 1 file"));
});

test("web pages are numbered W1, W2 and document passages keep 1, 2", () => {
  const c = page();
  const list = c.ragCiteList([{ web: true }, { path: "a.md" }, { web: true }, { path: "b.md" }]);
  assert.deepEqual(Array.from(list, (x) => x.label), ["W1", "1", "W2", "2"]);
});

test("a source shows file with extension, page, sheet and section", () => {
  const c = page();
  assert.equal(c.ragCiteFile({ title: "guide.md", path: "guide.md" }), "guide.md");
  assert.equal(c.ragCiteWhere({ heading: "Page 9" }), "page 9");
  assert.equal(c.ragCiteWhere({ heading: "Sheet: Orders" }), "sheet Orders");
  assert.equal(c.ragCiteWhere({ heading: "Refund policy" }), "under “Refund policy”");
  assert.equal(c.ragCiteWhere({ sheet: "Q2", heading: "" }), "sheet Q2");
  const row = c.ragCitesHtml([{ chunk_id: 9, title: "manual.pdf", path: "manual.pdf", heading: "Page 9", excerpt: "t" }], "s1");
  assert.ok(row.includes("manual.pdf") && row.includes("page 9"));
  const sheet = c.ragCitesHtml([{ chunk_id: 9, title: "orders.xlsx", path: "orders.xlsx", heading: "Sheet: Orders", excerpt: "t" }], "s1");
  assert.ok(sheet.includes('data-rows-for="9"'), "sheet rows are filled in from the host");
});

test("a calculated answer says it was calculated, not that passages were read", () => {
  const c = page();
  const out = c.ragCitesHtml([{ path: "/x/sales.xlsx", title: "sales.xlsx", sheet: "Q1", sql: "SELECT 1" }], "s1");
  assert.ok(out.includes("Calculated from 1 file") && !out.includes("passage"));
});

test("untrusted text in a source is never markup", () => {
  const c = page();
  const out = c.ragCitesHtml([{ chunk_id: 1, title: '<img src=x onerror=alert(1)>.md', path: "x", heading: '"><script>1</script>', excerpt: "<b>hi</b>" }], "s1");
  assert.ok(!/<img|<script|<b>/.test(out), out);
});

// Rows are generated here and the expected figures are summed here, not read from the app.
const ROWS = Array.from({ length: 400 }, (_, i) => ({ region: ["North", "South", "East", "West"][i % 4], amount: (i * 37) % 500 }));
const NORTH = ROWS.filter((r) => r.region === "North");
const sumNorth = NORTH.reduce((s, r) => s + r.amount, 0);

test("spreadsheet answer says what was calculated, from where and how many rows", () => {
  const c = page();
  const prov = {
    sql: "SELECT SUM(Amount) FROM Orders WHERE Region = 'North'", sheet: "Orders", workbook: "orders.xlsx",
    rows_matched: NORTH.length, rows_total: ROWS.length, abstained: false, operation: "SUM", filter: "Region is North",
    value: sumNorth, values_used: NORTH.length, assumed: [], linked: { metric: "Amount", filters: ["Region"] },
  };
  const l = c.ragProvenanceLines(prov);
  assert.equal(l.main, `Sum of Amount where Region is North: ${sumNorth.toLocaleString("en-US")}, from orders.xlsx, sheet Orders, ${NORTH.length} of ${ROWS.length} rows.`);
  assert.match(c.ragProvenanceHtml(prov), /Show the calculation/);
});

test("per-sheet and per-group figures and assumptions are listed; blanks are named", () => {
  const c = page();
  const l = c.ragProvenanceLines({
    workbook: "sales.xlsx", sheet: "Q1, Q2", operation: "SUM", group_by: "Region", rows_matched: 6, rows_total: 6,
    linked: { metric: "Revenue" }, sheets: [{ sheet: "Q1", rows_matched: 3, rows_total: 3 }, { sheet: "Q2", rows_matched: 3, rows_total: 3 }],
    groups: [{ group: "East", value: 3200 }, { group: "North", value: 2500 }], assumed: ["no column was named, so every row was counted"],
    values_used: 5,
  });
  assert.equal(l.main, "Sum of Revenue by Region, from sales.xlsx, sheets Q1, Q2, 6 of 6 rows.");
  assert.deepEqual(Array.from(l.more), [
    "Q1: 3 of 3 rows", "Q2: 3 of 3 rows", "East: 3,200", "North: 2,500",
    "Only 5 of the 6 matching rows had a number in this column. The others were left out.",
    "Assumed: no column was named, so every row was counted",
  ]);
  const two = c.ragProvenanceLines({ workbook: "sales.xlsx", sheet: "Q1, Q2", operation: "SUM", value: 7400, rows_matched: 6, rows_total: 6,
    linked: { metric: "Revenue" }, sheets: [{ sheet: "Q1", value: 3500, rows_matched: 3, rows_total: 3 }, { sheet: "Q2", value: 3900, rows_matched: 3, rows_total: 3 }] });
  assert.deepEqual(Array.from(two.more), ["Q1: 3,500 (3 of 3 rows)", "Q2: 3,900 (3 of 3 rows)"]);
  assert.equal(c.ragProvenanceLines({ abstained: true, rows_total: 400 }).main, "No figure was calculated. The sheet has 400 rows.");
  assert.equal(c.ragProvenanceLines({ workbook: "orders.csv", sheet: "orders", operation: "COUNT", value: 10, rows_matched: 10, rows_total: 10 }).main,
    "Count of rows: 10, from orders.csv, 10 of 10 rows.");
});

test("honesty notes: not found, unsupported statements, web results", () => {
  const c = page();
  const gap = c.ragNotesHtml({ goal: { verdict: "unsupported" }, stop_reason: "gaps_disclosed" }, []);
  assert.ok(gap.includes("Not found in your documents"));
  assert.ok(!gap.includes("Some statements"), "one clear message, not two");
  const abst = c.ragNotesHtml({ abstained: true }, []);
  assert.ok(abst.includes("Not found in your documents"));
  const part = c.ragNotesHtml({ goal: { verdict: "answerable" }, unsupported_claims: ["The CEO is Ann <b>x</b>"] }, [{ path: "a.md" }]);
  assert.ok(part.includes("Some statements were not found in the sources") && part.includes("The CEO is Ann"));
  assert.ok(!part.includes("<b>x</b>"), "claims are text");
  const web = c.ragNotesHtml({ web_used: true, goal: {} }, [{ web: true }]);
  assert.ok(web.includes("This answer used web results"));
  const calc = c.ragNotesHtml({ lane: "sql", goal: {}, provenance: { abstained: true, rows_total: 400 } }, []);
  assert.equal((calc.match(/No figure was calculated/g) || []).length, 1, "said once");
  assert.ok(calc.includes("The sheet has 400 rows."));
  const fine = c.ragNotesHtml({ goal: { verdict: "answerable" }, unsupported_claims: [], faithfulness: 1 }, [{ path: "a.md" }]);
  assert.equal(fine, "", "a grounded answer shows no warning");
  assert.ok(!c.ragNotesHtml({ lane: "sql", goal: {}, provenance: { workbook: "o.xlsx", sheet: "O", operation: "SUM", value: 1, rows_matched: 1, rows_total: 1 } }, []).includes("Not found"));
});

test("upload report names every skipped file and counts honestly", () => {
  const c = page();
  const none = c.ragUploadSummary(2, {
    sources: 0, chunks: 0,
    skipped: [{ path: "bad.pdf", reason: "not a readable PDF (corrupt or truncated)" }, { path: "scan.png", reason: "no extractable text" }],
  }, []);
  assert.equal(none.headline, "Nothing was added. 2 not added:");
  assert.equal(none.added, 0);
  assert.match(none.problems[0], /^bad\.pdf could not be opened as a PDF/);
  assert.match(none.problems[1], /^scan\.png has no text it can read\. .*OCR/);
  const mixed = c.ragUploadSummary(2, { sources: 1, chunks: 48, skipped: [{ path: "empty.txt", reason: "no extractable text" }] }, ["blob.bin"]);
  assert.equal(mixed.headline, "Added 1 file. 48 searchable pieces made. 2 not added:");
  assert.match(mixed.problems[0], /^blob\.bin looks like a program or data file/);
  assert.match(mixed.problems[1], /^empty\.txt is empty/);
  assert.equal(mixed.problems.length, 2, "the refused file and the skipped file, nothing double counted");
});

test("the same file added again is not reported as added", () => {
  const c = page();
  const again = c.ragUploadSummary(1, { sources: 1, chunks: 0, skipped: [] }, []);
  assert.equal(again.headline, "1 file was already in this space. Nothing new was added.");
  assert.equal(again.problems.length, 0);
});

test("a binary file with an unknown extension is refused, known types and text are not", async () => {
  const c = page();
  const file = (name, bytes) => ({ name, slice: () => ({ arrayBuffer: async () => new Uint8Array(bytes).buffer }) });
  assert.equal(await c.ragLooksBinary(file("blob.bin", [1, 2, 0, 4])), true);
  assert.equal(await c.ragLooksBinary(file("notes.txt", [104, 105, 10])), false);
  assert.equal(await c.ragLooksBinary(file("manual.pdf", [37, 80, 0, 0])), false, "documents go to the server");
  assert.equal(await c.ragLooksBinary(file("data.xlsx", [80, 75, 0, 0])), false);
});

test("source tile shows size", () => {
  const c = page();
  assert.equal(c.ragBytes(65700), "64 KB");
  assert.equal(c.ragBytes(69), "69 B");
  assert.equal(c.ragBytes(0), "");
});
