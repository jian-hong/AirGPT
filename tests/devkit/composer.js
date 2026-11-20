// Browser check for the message box (composer.1 to composer.12, voice input) against the stand-in model.
//
//   python3 tests/devkit/composer_fixtures.py <fixtures-dir>
//   BASE_URL=http://127.0.0.1:<port> node tests/devkit/composer.js <shots-dir> <stub-log.jsonl> <fixtures-dir>
//
// Ends with "RESULT n pass, m fail".
const { chromium } = require('playwright');
const fs = require('fs');
const [out, logPath, fx] = process.argv.slice(2);
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8770';
const fail = []; let pass = 0;
const check = (name, ok, detail) => { if (ok) pass++; else fail.push(name); console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail ? ' :: ' + detail : '')); };
const reqs = () => fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8').trim().split('\n').filter(Boolean).map(l => JSON.parse(l)) : [];
const modelSaw = from => reqs().slice(from).map(r => JSON.stringify(r.messages)).join('\n');
const nreq = () => reqs().length;
const FILTER_SMALL = r => !(r.max_tokens && r.max_tokens <= 128);

async function open(b, opts = {}) {
  const ctx = await b.newContext(Object.assign({ viewport: { width: 1280, height: 800 } }, opts.ctx || {}));
  if (opts.init) await ctx.addInitScript(opts.init);
  const p = await ctx.newPage();
  p.errs = []; p.on('pageerror', e => { const m = String(e); if (!/anonymous define/.test(m)) p.errs.push(m.slice(0, 160)); });
  await p.goto(BASE + '/', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(2500);
  return { ctx, p };
}
async function answered(p, before) {
  await p.waitForFunction(n => document.querySelectorAll('#chat .msg.ai-msg[id^="msg-"]').length > n && !document.getElementById('ai-stream'), before, { timeout: 60000 });
  await p.waitForTimeout(700);
}
const nAi = p => p.locator('#chat .msg.ai-msg[id^="msg-"]').count();
async function ask(p, q, files) {
  const n = await nAi(p);
  if (files) { await p.setInputFiles('#fileIn', files.map(f => `${fx}/${f}`)); await p.waitForTimeout(300); }
  await p.fill('#input', q); await p.press('#input', 'Enter');
  await answered(p, n);
}
const noSideScroll = p => p.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1 && document.body.scrollWidth <= innerWidth + 1);

(async () => {
  const b = await chromium.launch();

  // ---------- desktop ----------
  let { ctx, p } = await open(b);
  // composer.1: facts only present in the file reach the model, for every readable type
  for (const [f, fact] of [['notes.txt', 'SECRET-42'], ['data.csv', 'CSV-7788'], ['data.json', 'JSON-5521'], ['readme.md', 'MD-3344'],
                           ['real.pdf', 'PDF-GATE-7731'], ['notes.docx', 'DOCX-LOCKER-5512'], ['sheet.xlsx', 'XLSX-9090']]) {
    const from = nreq();
    await ask(p, `What is in the attached file ${f}?`, [f]);
    const saw = modelSaw(from);
    check(`attach ${f} reaches the model`, saw.includes(fact) && /untrusted file content/.test(saw));
  }
  // two files at once
  let from = nreq();
  await ask(p, 'Read both attached files.', ['notes.txt', 'data.csv']);
  let saw = modelSaw(from);
  check('two files at once', saw.includes('SECRET-42') && saw.includes('CSV-7788'));
  // injection text arrives fenced and labelled
  from = nreq();
  await ask(p, 'Summarise the attached file.', ['evil.txt']);
  saw = modelSaw(from);
  check('injection text is inside the untrusted fence', /untrusted file content[\s\S]*<<<FILE \\"evil.txt\\">>>[\s\S]*ignore previous instructions[\s\S]*<<<END FILE>>>/.test(saw));
  // image plus text file: the file still reaches the model
  from = nreq();
  await ask(p, 'Here is a picture and a note.', ['pic.png', 'notes.txt']);
  check('image plus text file', modelSaw(from).includes('SECRET-42'));
  // unreadable: scanned pdf, empty file, 40 MB pdf are named with a reason, nothing crashes
  await p.setInputFiles('#fileIn', [`${fx}/scan.pdf`]); await p.fill('#input', 'What does the scan say?'); await p.press('#input', 'Enter');
  await p.waitForSelector('#uploadProg.warn', { timeout: 20000 });
  check('scanned pdf is named with a reason', /scan\.pdf[^]*cannot read it[^]*no readable text/.test(await p.textContent('#uploadProg')));
  await answered(p, (await nAi(p)) - 1).catch(() => {});
  await p.reload(); await p.waitForTimeout(2500);
  await p.setInputFiles('#fileIn', [`${fx}/empty.txt`]); await p.waitForTimeout(300);
  check('empty file is refused at staging', await p.evaluate(() => stagedFiles.length) === 0 && /empty/.test(await p.textContent('#toast')));
  from = nreq();
  await p.setInputFiles('#fileIn', [`${fx}/big40.pdf`]); await p.fill('#input', 'Read the big pdf BIGQ'); await p.press('#input', 'Enter');
  await p.waitForSelector('#uploadProg.warn', { timeout: 60000 });
  check('40 MB pdf is stored but named as too large to read', /big40\.pdf[^]*too large to read/.test(await p.textContent('#uploadProg')));
  await p.waitForTimeout(3000);
  check('40 MB pdf text did not reach the model', !modelSaw(from).includes('BIG-PDF-9999'));
  // prompt panel adds up with attachments present and absent
  const trace = async () => p.evaluate(async () => {
    const rows = [...document.querySelectorAll('#chat .msg.ai-msg[id^="msg-"]')]; const id = rows[rows.length - 1].id.replace('msg-', '');
    return (await (await api('/api/chat/prompt-trace?message_id=' + id)).json());
  });
  await p.reload(); await p.waitForTimeout(2500);
  await ask(p, 'Plain question without a file TRACE-A');
  let t = await trace(); let tr = t.trace || t;
  check('trace without file adds up', tr.sections && !tr.sections.some(s => s.key === 'attachments') && tr.total_chars === tr.sections.reduce((a, s) => a + s.chars, 0));
  await ask(p, 'Question with a file TRACE-B', ['notes.txt']);
  t = await trace(); tr = t.trace || t;
  const sec = (tr.sections || []).find(s => s.key === 'attachments');
  check('trace with file has its own section', !!sec && sec.label === 'Attached files' && tr.total_chars === tr.sections.reduce((a, s) => a + s.chars, 0));

  // composer.12 project box does not overwrite the main box, has attach and the / menu
  await p.evaluate(() => { showProjectFocus('general') });
  await p.waitForSelector('#projComposeInput', { timeout: 8000 });
  check('project box has aria-label and attach button', (await p.getAttribute('#projComposeInput', 'aria-label')) && (await p.locator('#projAttach').count()) === 1);
  await p.type('#projComposeInput', '/ra'); await p.waitForTimeout(900);
  check('project box has the / menu', await p.evaluate(() => { const m = document.getElementById('composerAc'); return !!m && m.style.display !== 'none' && m.children.length > 0 }));
  await p.fill('#projComposeInput', ''); await p.evaluate(() => { document.getElementById('composerAc').style.display = 'none' });
  await p.evaluate(() => { $('input').value = 'MAIN-BOX-KEEP'; });
  await p.fill('#projComposeInput', 'Project question PROJQ');
  const nb = await nAi(p);
  await p.click('#projComposeSend');
  await p.waitForFunction(() => !!document.getElementById('ai-stream') || document.querySelectorAll('#chat .msg').length > 0, null, { timeout: 15000 });
  await p.waitForTimeout(6000);
  check('project box leaves the main box alone', (await p.inputValue('#input')) === 'MAIN-BOX-KEEP', await p.inputValue('#input'));
  await p.fill('#input', '');

  // composer.2 long message: counter + cut reported in the reply area
  await p.fill('#input', 'x'.repeat(5200)); await p.waitForTimeout(200);
  check('count shows near the limit', /5,200 \/ 6,000/.test(await p.textContent('#charCount')) && await p.isVisible('#charCount'));
  await p.fill('#input', 'y'.repeat(20000)); await p.waitForTimeout(200);
  check('count shows the cut when over', /20,000 \/ 6,000[^]*first 6,000/.test(await p.textContent('#charCount')));
  await p.screenshot({ path: `${out}/d-count.png` });
  from = nreq();
  const nl = await nAi(p); await p.press('#input', 'Enter'); await answered(p, nl);
  const longReply = await p.evaluate(() => [...document.querySelectorAll('#chat .msg.ai-msg[id^="msg-"]')].pop().innerText);
  check('cut is said in the reply area', /longer than 6,000 characters/.test(longReply), longReply.slice(0, 120));
  check('model got at most 6,000 of it', (modelSaw(from).match(/y/g) || []).length <= 6100);
  await p.fill('#input', 'z'.repeat(100)); await p.waitForTimeout(100);
  check('count hidden for a short message', !(await p.isVisible('#charCount')));
  await p.fill('#input', '');

  // composer.9 slash menu and Enter
  const n9 = await nAi(p);
  await p.fill('#input', ''); await p.type('#input', 'please explain the /rag'); await p.waitForTimeout(700);
  const acOpen = await p.evaluate(() => { const m = document.getElementById('composerAc'); return !!m && m.style.display !== 'none' });
  from = nreq(); await p.press('#input', 'Enter'); await answered(p, n9);
  check('"please explain the /rag" + Enter sends', acOpen && /please explain the \/rag/.test(modelSaw(from)));
  await p.fill('#input', ''); await p.type('#input', '/rag'); await p.waitForTimeout(700);
  await p.press('#input', 'Enter'); await p.waitForTimeout(300);
  check('"/rag" at the start still picks on Enter', /^\/rag\s/.test(await p.inputValue('#input')), await p.inputValue('#input'));
  await p.fill('#input', ''); await p.type('#input', 'use the /'); await p.waitForTimeout(700);
  await p.press('#input', 'ArrowDown'); await p.press('#input', 'Enter'); await p.waitForTimeout(300);
  check('arrow then Enter picks mid-text', /^use the \/\w+/.test(await p.inputValue('#input')) && (await p.inputValue('#input')).length > 'use the /'.length, await p.inputValue('#input'));
  await p.fill('#input', ''); await p.type('#input', 'a /'); await p.waitForTimeout(700);
  const aria = await p.evaluate(() => ({ role: document.getElementById('composerAc').getAttribute('role'), opt: document.querySelector('#composerAc [role=option]') && true, ad: document.getElementById('input').getAttribute('aria-activedescendant'), ex: document.getElementById('input').getAttribute('aria-expanded') }));
  check('menu has listbox/option roles and activedescendant', aria.role === 'listbox' && aria.opt && /^acOpt\d+$/.test(aria.ad || '') && aria.ex === 'true', JSON.stringify(aria));
  await p.fill('#input', '');

  // IME composition never sends
  const cdp = await ctx.newCDPSession(p);
  await p.fill('#input', ''); await p.focus('#input');
  const nI = nreq();
  await cdp.send('Input.imeSetComposition', { text: 'ni hao', selectionStart: 6, selectionEnd: 6 });
  await p.keyboard.press('Enter'); await p.waitForTimeout(1200);
  check('Enter does not send while an input method composes', nreq() === nI);
  await cdp.send('Input.insertText', { text: '' }).catch(() => {}); await p.fill('#input', '');

  // composer.7 drafts
  await p.fill('#input', 'DRAFT-ONE unsent'); await p.waitForTimeout(700);
  const keyA = await p.evaluate(() => draftKey());
  await p.reload(); await p.waitForTimeout(2500);
  check('draft survives a reload', (await p.inputValue('#input')) === 'DRAFT-ONE unsent', await p.inputValue('#input'));
  await p.evaluate(() => { const k = draftKey(); return k }); // chat A is the open chat
  const sidA = await p.evaluate(() => currentSession);
  await p.click('#sideNewChat, [data-call="newChat"], .new-chat-btn', { timeout: 2000 }).catch(async () => { await p.evaluate(() => { newChat && newChat() }) });
  await p.waitForTimeout(800);
  const inNew = await p.inputValue('#input');
  check('a different chat does not show chat A\'s draft', inNew !== 'DRAFT-ONE unsent', inNew);
  await p.evaluate(s => openSession(s), sidA); await p.waitForTimeout(1200);
  check('switching back restores chat A\'s draft', (await p.inputValue('#input')) === 'DRAFT-ONE unsent', await p.inputValue('#input'));
  const nd = await nAi(p); await p.press('#input', 'Enter'); await answered(p, nd);
  await p.waitForTimeout(600);
  await p.reload(); await p.waitForTimeout(2500);
  check('draft is gone after sending', (await p.inputValue('#input')) === '' && (await p.evaluate(() => Object.keys(localStorage).filter(k => k.startsWith('airgpt_draft:') && localStorage[k].includes('DRAFT-ONE')).length)) === 0, JSON.stringify([await p.inputValue('#input'), await p.evaluate(() => Object.entries(localStorage).filter(([k]) => k.startsWith('airgpt_draft')))]));

  // composer.8 bug button never covers Send
  let cover = [];
  for (const n of [1, 3, 5, 8, 12]) {
    await p.fill('#input', Array(n).fill('line').join('\n')); await p.waitForTimeout(600);
    const r = await p.evaluate(() => { const g = e => document.querySelector(e).getBoundingClientRect(); const s = g('#sendBtn'), f = g('#bugReportBtn'); return { hit: f.right > s.left && f.left < s.right && f.bottom > s.top && f.top < s.bottom, vis: s.width > 0 } });
    if (r.hit && r.vis) cover.push(n);
  }
  check('bug button never covers Send (1..12 lines)', cover.length === 0, cover.join(','));
  await p.fill('#input', ''); 
  check('no page errors on desktop', p.errs.length === 0, p.errs.join(' | '));
  await ctx.close();

  // ---------- no SpeechRecognition ----------
  ({ ctx, p } = await open(b, { init: () => { delete window.SpeechRecognition; delete window.webkitSpeechRecognition; } }));
  check('mic button absent without SpeechRecognition', (await p.locator('#micBtn').count()) === 0);
  await ctx.close();

  // ---------- with a fake SpeechRecognition ----------
  ({ ctx, p } = await open(b, { init: () => {
    class SR { start() { window.__sr = this; this.started = true; } stop() { this.onend && this.onend(); } }
    window.SpeechRecognition = SR; window.webkitSpeechRecognition = SR;
  } }));
  check('mic button present with SpeechRecognition', (await p.locator('#micBtn').count()) === 1);
  const n0 = nreq();
  await p.fill('#input', 'before'); await p.click('#micBtn'); await p.waitForTimeout(200);
  check('listening is shown', (await p.getAttribute('#micBtn', 'aria-pressed')) === 'true' && await p.isVisible('#voiceStatus'));
  await p.screenshot({ path: `${out}/d-listening.png` });
  await p.evaluate(() => { const r = window.__sr; const mk = (t, f) => { const x = [{ transcript: t }]; x.isFinal = f; return x; }; r.onresult({ resultIndex: 0, results: [mk('hello there', true), mk('and more', false)] }); });
  check('speech fills the box and does not send', (await p.inputValue('#input')) === 'before hello there and more' && nreq() === n0, await p.inputValue('#input'));
  await p.click('#micBtn'); await p.waitForTimeout(200);
  check('listening stops on a second tap', (await p.getAttribute('#micBtn', 'aria-pressed')) === 'false' && !(await p.isVisible('#voiceStatus')));
  await p.click('#micBtn'); await p.evaluate(() => window.__sr.onerror({ error: 'not-allowed' })); await p.waitForTimeout(200);
  check('a blocked microphone is explained', /microphone is blocked/i.test(await p.textContent('#toast')));
  await ctx.close();

  // ---------- phone ----------
  for (const theme of ['dark', 'light']) {
    ({ ctx, p } = await open(b, { ctx: { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, deviceScaleFactor: 2 }, init: theme === 'light' ? () => localStorage.setItem('airgpt_theme', 'light') : undefined }));
    if (theme === 'dark') {
      // composer.6 Return is a new line on touch, Send sends
      const nph = nreq();
      await p.fill('#input', 'line one'); await p.focus('#input'); await p.keyboard.press('Enter'); await p.keyboard.type('line two'); await p.waitForTimeout(500);
      check('phone: Return makes a new line and does not send', (await p.inputValue('#input')) === 'line one\nline two' && nreq() === nph, JSON.stringify(await p.inputValue('#input')));
      check('phone: enterkeyhint is enter', (await p.getAttribute('#input', 'enterkeyhint')) === 'enter');
      const nq = await nAi(p); await p.click('#sendBtn'); await answered(p, nq);
      check('phone: Send button sends', /line one/.test(modelSaw(nph)));
      // composer.10 the + button and its sheet
      const sizes = await p.evaluate(() => ['attachBtn', 'sendBtn'].map(i => { const r = document.getElementById(i).getBoundingClientRect(); return [i, Math.round(r.width), Math.round(r.height)] }));
      check('phone: + is 44px', sizes[0][1] >= 44 && sizes[0][2] >= 44, JSON.stringify(sizes));
      await p.click('#attachBtn'); await p.waitForTimeout(400);
      const sheet = await p.evaluate(() => [...document.querySelectorAll('#plusMenu button')].filter(b => b.offsetParent).map(b => [b.textContent.trim().slice(0, 14), Math.round(b.getBoundingClientRect().height)]));
      const names = sheet.map(x => x[0]).join('|');
      check('phone sheet has Effort, Web search, Thinking, Instructions', /Basic/.test(names) && /Web search/.test(names) && /Thinking/.test(names) && /Instructions/.test(names), names);
      check('phone sheet targets are 44px', sheet.every(x => x[1] >= 44), JSON.stringify(sheet));
      await p.screenshot({ path: `${out}/p-sheet.png` });
      await p.click('#plusMenu [data-pm-tier="max"]'); await p.waitForTimeout(200);
      check('phone sheet changes effort', await p.evaluate(() => modelTier) === 'max');
      await p.click('#plusMenu [data-pm="think"]'); await p.waitForTimeout(200);
      check('phone sheet toggles thinking', (await p.evaluate(() => thinkingEnabled)) === false);
      await p.evaluate(() => { setModelTier('high'); thinkingEnabled = true; localStorage.setItem('airgpt_thinking', '1') });
      await p.click('#attachBtn'); await p.click('#plusMenu [data-pm="prefs"]'); await p.waitForTimeout(500);
      check('phone sheet opens Instructions', await p.evaluate(() => !!document.querySelector('.cprefs-sheet.open')));
      await p.keyboard.press('Escape'); await p.evaluate(() => { document.querySelector('.cprefs-sheet.open')?.classList.remove('open') });
      // project box + rag box Return on touch
      await p.evaluate(() => showProjectFocus('general')); await p.waitForSelector('#projComposeInput');
      const np = nreq(); await p.fill('#projComposeInput', 'a'); await p.focus('#projComposeInput'); await p.keyboard.press('Enter'); await p.keyboard.type('b'); await p.waitForTimeout(400);
      check('phone: project box Return is a new line', (await p.inputValue('#projComposeInput')) === 'a\nb' && nreq() === np);
      await p.evaluate(() => { $('input').value = ''; });
    }
    check(`phone ${theme}: no sideways scroll`, await noSideScroll(p));
    await p.evaluate(() => newChat && newChat()); await p.waitForTimeout(600);
    await p.fill('#input', 'a\nb\nc\nd\ne'); await p.waitForTimeout(400);
    const hit = await p.evaluate(() => { const g = e => document.querySelector(e).getBoundingClientRect(); const s = g('#sendBtn'), f = g('#bugReportBtn'); const vis = getComputedStyle(document.getElementById('bugReportBtn')).display !== 'none'; return vis && f.right > s.left && f.left < s.right && f.bottom > s.top && f.top < s.bottom });
    check(`phone ${theme}: bug button off Send`, !hit);
    await p.screenshot({ path: `${out}/p-${theme}.png` });
    await ctx.close();
  }
  // desktop light, no sideways scroll
  ({ ctx, p } = await open(b, { init: () => localStorage.setItem('airgpt_theme', 'light') }));
  await p.fill('#input', 'q'.repeat(5400)); await p.waitForTimeout(300);
  check('desktop light: no sideways scroll', await noSideScroll(p));
  await p.screenshot({ path: `${out}/d-light.png` });
  await ctx.close();

  await b.close();
  console.log(`RESULT ${pass} pass, ${fail.length} fail` + (fail.length ? ' :: ' + fail.join('; ') : ''));
  process.exit(fail.length ? 1 : 0);
})();
