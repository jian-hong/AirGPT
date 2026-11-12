/** Pure blank parsing and filling for ui/snippets.js. Run: node --test tests/snippets.test.mjs */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { parseBlanks, fill } = require("../ui/snippets.js");

test("finds each distinct blank once, in order", () => {
  assert.deepEqual(parseBlanks("Hi {{name}}, re {{topic}}. Bye {{name}}."), ["name", "topic"]);
});

test("spaces inside braces are trimmed", () => {
  assert.deepEqual(parseBlanks("{{  name }} and {{name}}"), ["name"]);
  assert.equal(fill("Dear {{ name }}", { name: "Sam" }), "Dear Sam");
});

test("no blanks gives an empty list and unchanged text", () => {
  assert.deepEqual(parseBlanks("plain text"), []);
  assert.equal(fill("plain text", {}), "plain text");
});

test("a repeated blank is filled everywhere", () => {
  assert.equal(fill("{{a}}-{{a}}-{{b}}", { a: "1", b: "2" }), "1-1-2");
});

test("missing or empty values leave nothing that looks like a blank", () => {
  assert.equal(fill("a {{x}} b {{y}} c", { y: "" }), "a  b  c");
  assert.equal(fill("a {{x}}", null), "a ");
  assert.doesNotMatch(fill("{{x}}{{ y }}", {}), /\{\{/);
});

test("an unclosed or empty brace pair is left alone", () => {
  assert.deepEqual(parseBlanks("open {{ never closed"), []);
  assert.equal(fill("open {{ never closed", { never: "x" }), "open {{ never closed");
  assert.deepEqual(parseBlanks("empty {{}} and {{  }}"), []);
  assert.equal(fill("empty {{}}", {}), "empty {{}}");
});

test("a value that contains a blank is not filled again", () => {
  assert.equal(fill("{{a}}", { a: "{{b}}", b: "no" }), "{{b}}");
});

test("a name like toString does not pull in object internals", () => {
  assert.equal(fill("{{toString}}", {}), "");
});

test("values containing dollar signs are inserted literally", () => {
  assert.equal(fill("{{a}}", { a: "$& $1" }), "$& $1");
});

test("blanks named like object internals are still asked for and filled", () => {
  assert.deepEqual(parseBlanks("{{__proto__}} {{constructor}} {{toString}}"), ["__proto__", "constructor", "toString"]);
  const v = Object.create(null);
  v["__proto__"] = "P"; v["constructor"] = "C";
  assert.equal(fill("{{__proto__}}/{{constructor}}", v), "P/C");
});
