// Guards the responsive lane: each check names a defect that was seen in a browser
// (see the lane report) and fails on the code that had it.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const read = (p) => fs.readFileSync(new URL('../' + p, import.meta.url), 'utf8');
const html = read('index.html');
const phone = read('ui/phone.css').replace(/\/\*[\s\S]*?\*\//g, '');
const ide = read('OpenIDE/ui/openide.css');

test('OpenIDE: a phone gets one column, and collapsed rails cannot undo the single column', () => {
  assert.match(ide, /@media\(max-width:760px\)\{body\.openide-mode \.app,body\.openide-mode \.app\.side-collapsed\{grid-template-columns:minmax\(0,1fr\)\}\}/);
  const m = ide.match(/@media\(max-width:960px\)\{[\s\S]*$/);
  assert.ok(m && /\.openide-shell\.right-collapsed[\s\S]*grid-template-columns:minmax\(0,1fr\)/.test(m[0]));
});

test('tablet: an open sidebar floats over the chat between 761 and 960px', () => {
  assert.match(html, /@media\(min-width:761px\) and \(max-width:960px\)\{[^}]*\.app:not\(\.side-collapsed\)[^}]*grid-template-columns:0 minmax\(0,1fr\)\}[\s\S]*?\.app:not\(\.side-collapsed\) \.side\{position:absolute/);
});

test('the Thinking button and the Manual/AI cue stay at 900px and below', () => {
  const block = html.match(/@media\(max-width:900px\)\{[\s\S]*?\n\}/)[0];
  assert.ok(!/\.think-btn\{display:none\}/.test(block));
  assert.ok(!/\.ai-switch-label\{display:none\}/.test(block));
  assert.match(block, /\.ai-switch-label:not\(\.on\)\{display:none\}/);
  // Attribute order is not the point: the switch must say it is a switch and carry its state.
  const sw = /<button[^>]*id="aiSwitchBtn"[^>]*>/.exec(html);
  assert.ok(sw, "the Manual/AI switch button exists");
  assert.match(sw[0], /role="switch"/);
  assert.match(sw[0], /aria-checked="false"/);
});

test('bug report: pointer events, one Esc meaning, and a button that says what it does', () => {
  assert.ok(!/ov\.addEventListener\('mousedown'/.test(html));
  assert.match(html, /ov\.addEventListener\('pointerdown',onDown\)/);
  assert.match(html, /#bugOverlay\{[^}]*touch-action:none/);
  assert.ok(!html.includes('Esc / Exit'));
  // the page-wide Esc handler must leave the mark step to the report code
  assert.match(html, /if\(document\.getElementById\('bugOverlay'\)\)return;/);
  assert.ok(!/document\.getElementById\('bugRecBar'\)\?\.style\?\.display==='inline-flex'\)\{\s*e\.preventDefault\(\);window\.__bugCancel/.test(html));
});

test('floating bug button hides behind any open panel that carries .fab-hide', () => {
  assert.match(html, /body:has\(\.fab-hide\.open\) #bugReportBtn\{display:none\}/);
  for (const marker of ['class="model-dd fab-hide"', 'class="mem-overlay fab-hide"', "panel.className = 'fab-hide'"]) assert.ok(html.includes(marker), marker);
});

test('Background tasks panel closes on Escape and outside click and stops above the message box', () => {
  const i = html.indexOf('Background tasks panel');
  const bg = html.slice(i);
  assert.match(bg, /e\.key === 'Escape'/);
  assert.match(bg, /document\.addEventListener\('click'/);
  assert.match(bg, /panel\.style\.bottom = gap/);
});

test('OpenForge Design button does not stretch in the flex column', () => {
  assert.match(html, /\.forge-left \.btn\{flex:none\}/);
});

test('login dialog: host block hidden when joining, passcode field has no stray margin', () => {
  assert.match(html, /\$\('loginHostPane'\)\.style\.display=st\.initialized\?'none':''/);
  assert.match(html, /id="modalJoinPass" class="side-search" style="width:100%;margin:0 0 12px"/);
});

test('phone.css: 16px fields, 44px dialog buttons, checkbox rows, docked report bar', () => {
  assert.match(phone, /textarea,select\{font-size:16px!important\}/);
  assert.match(phone, /#settingsModal \.modal-actions \.btn[^{]*\{min-height:44px\}/);
  assert.match(phone, /#settingsModal \.settings-check\{min-height:44px\}/);
  assert.match(phone, /body #bugRecBar\{top:calc/);
  assert.match(phone, /\.composer-row #input\{order:-1/);
});

test('memory Search button uses the shared button style', () => {
  assert.match(html, /<button type="button" class="btn" onclick="runMemSearch\(\)">Search<\/button>/);
});

test('bug report: every Esc hint agrees (Esc leaves the mark step, Cancel ends the report) and a sideways phone docks the bar', () => {
  assert.ok(!/Esc cancels mark \/ exits/.test(html));
  assert.match(html, /Esc leaves the mark step\. Cancel ends the report\./);
  assert.match(html, /@media\(pointer:coarse\) and \(max-height:500px\)\{body #bugRecBar\{top:8px;bottom:auto\}\}/);
});
