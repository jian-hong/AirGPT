// The Open action (iOS native preview) must show for pdf/office/txt messages and
// never for html/svg/xml/images/video/text. Logic is lifted out of index.html.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const re = html.match(/const OPEN_EXT=[^\n]+\n/)[0];
const fn = html.match(/function canOpenInTab\(m\)\{[^\n]+\}\n/)[0];
const canOpenInTab = new Function(`${re}${fn}return canOpenInTab`)();
const msg = (filename, kind = 'file') => ({ filename, filepath: 'files/' + filename, kind });

test('Open is offered for pdf and office files', () => {
  for (const n of ['a.pdf', 'A.PDF', 'b.docx', 'b.doc', 'c.xlsx', 'c.xls', 'd.pptx', 'd.ppt', 'n.txt'])
    assert.equal(canOpenInTab(msg(n)), true, n);
});
test('Open is never offered for script-capable, image, video or text messages', () => {
  for (const n of ['a.html', 'a.htm', 'a.svg', 'a.xml', 'a.js', 'a.pdf.html', 'a.exe', 'noext'])
    assert.equal(canOpenInTab(msg(n)), false, n);
  assert.equal(canOpenInTab(msg('a.pdf', 'image')), false);
  assert.equal(canOpenInTab(msg('a.pdf', 'video')), false);
  assert.equal(canOpenInTab({ kind: 'text', text: 'x' }), false);
  assert.equal(canOpenInTab(null), false);
});
test('the Open buttons exist in the modal', () => {
  assert.ok(html.includes('id="mOpen"') && html.includes('id="mSpace"'));
  assert.ok(html.includes("a.rel='noopener noreferrer'"));
});
