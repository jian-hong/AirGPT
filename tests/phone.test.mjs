// Guards the phone lane: every rule in ui/phone.css must sit inside a
// max-width:760px media block, so laptop widths can never change.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const css = fs.readFileSync(new URL('../ui/phone.css', import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

test('phone.css only has rules inside @media(max-width:760px)', () => {
  let depth = 0, top = '';
  for (const ch of css) {
    if (ch === '{') { if (depth === 0) assert.match(top.trim(), /^@media\s*\(max-width:\s*760px\)$/); depth++; top = ''; }
    else if (ch === '}') { depth--; top = ''; }
    else if (depth === 0) top += ch;
  }
  assert.equal(depth, 0);
});

test('phone.js is loaded by the page and has valid syntax', () => {
  const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  assert.ok(html.includes('<script src="/ui/phone.js"></script>'));
  new Function(fs.readFileSync(new URL('../ui/phone.js', import.meta.url), 'utf8'));
});

test('phone icon row keeps the streaming Stop button readable and the Stopped mark in the one row', () => {
  // Stop reuses msg-copy; the phone icon rule must not turn it into the hidden-text Copy icon.
  const stop = css.match(/button#streamStopBtn\{[^}]*\}/);
  assert.ok(stop, 'rule for #streamStopBtn');
  assert.doesNotMatch(stop[0], /font-size:0/);
  assert.match(css, /button#streamStopBtn::before[^{]*\{content:none/);
  // The chip sits in the sixth column, after the five 44px icon columns, so it never opens a second row.
  const chip = css.match(/\.msg-stopped\{[^}]*\}/)[0];
  assert.match(chip, /grid-column:6/);
  assert.doesNotMatch(chip, /span/);
});
