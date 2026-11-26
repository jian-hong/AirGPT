// Browser regression check for the chat shell: sends messages through the real page
// against a stand-in model and checks instructions, saved prompts, command box, fork,
// export, prompt panel and the phone layout (27 checks).
//
//   BASE_URL=http://127.0.0.1:<port> node tests/devkit/integ.js <screenshots-dir> <stub-request-log.jsonl>
//
// Start the app with tests/devkit/run_app.py and the model with tests/devkit/stub_llm.py
// (an env.local in the checkout pointing OLLAMA_BASE_URL at it). Ends with "RESULT n pass, m fail".
const { chromium } = require('playwright');
const fs = require('fs');
const [out, logPath] = process.argv.slice(2);
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8770';
const R = {}; const fail = [];
const check = (name, ok, detail) => { R[name] = ok ? 'PASS' : 'FAIL'; if (!ok) fail.push(name + ': ' + (detail || '')); console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail ? ' :: ' + detail : '')); };
const lastReq = () => { const l = fs.readFileSync(logPath, 'utf8').trim().split('\n'); return JSON.parse(l[l.length - 1]); };
const userText = r => r.messages.filter(m => m.role === 'user').map(m => m.content).join('\n');
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2, acceptDownloads: true });
  const p = await ctx.newPage();
  const errs = []; let dialogs = 0;
  p.on('pageerror', e => { const m = String(e); if (!/anonymous define/.test(m)) errs.push(m.slice(0, 200)); });
  p.on('dialog', d => { dialogs++; d.dismiss(); });
  const send = async q => {
    const before = await p.locator('#chat .msg.ai-msg[id^="msg-"]').count();
    await p.fill('#input', q); await p.press('#input', 'Enter');
    await p.waitForFunction(n => document.querySelectorAll('#chat .msg.ai-msg[id^="msg-"]').length > n && !document.getElementById('ai-stream'), before, { timeout: 60000 });
    await p.waitForTimeout(900);
  };
  await p.goto(BASE + '/', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(3000);
  await send('We are planning the Penang office launch.');
  const sid1 = await p.evaluate(() => currentSession);

  // chat instructions
  await p.evaluate(() => ChatPrefs.open()); await p.waitForSelector('.cprefs-sheet.open textarea');
  await p.fill('.cprefs-sheet textarea', 'Always answer in Malay. INSTR-MARKER-123 <b>bold</b>');
  await p.screenshot({ path: `${out}/d-instructions.png` });
  await p.locator('.cprefs-sheet button', { hasText: /^Save/ }).first().click(); await p.waitForTimeout(900);
  const prefs = await p.evaluate(async s => (await (await api('/api/chat/prefs?session_id=' + s)).json()), sid1);
  check('instructions saved', /INSTR-MARKER-123/.test(prefs.instructions || ''));
  await p.keyboard.press('Escape'); await p.waitForTimeout(300);
  await send('Draft a short checklist.');
  check('instructions reached the model (provider log)', userText(lastReq()).includes('INSTR-MARKER-123'));
  await p.locator('#chat .msg.ai-msg .msg-lens').last().click(); await p.waitForSelector('.plens-sheet.open .plens-row');
  const rows = await p.locator('.plens-row summary strong').allInnerTexts();
  check('prompt panel lists Chat instructions', rows.some(t => /Chat instructions/.test(t)), rows.join(' | '));
  const trace = await p.evaluate(async s => (await (await api('/api/chat/prompt-trace?session_id=' + s)).json()).trace, sid1);
  const req = lastReq();
  const sysSent = (req.messages.find(m => m.role === 'system') || {}).content || '';
  const traceUser = trace.sections.filter(s => s.key !== 'system' && s.key !== 'tools').reduce((a, s) => a + s.chars, 0);
  check('panel size equals what was sent', traceUser === userText(req).length && trace.sections.find(s => s.key === 'system').text === sysSent, `trace ${traceUser} vs sent ${userText(req).length}`);
  await p.screenshot({ path: `${out}/d-lens-instructions.png` });
  await p.keyboard.press('Escape'); await p.waitForTimeout(300);

  // saved prompts (stored XSS attempt in the title and a blank)
  const mk = await p.evaluate(async () => { const r = await api('/api/snippets', { method: 'POST', body: JSON.stringify({ title: 'Status <img src=x onerror=alert(1)>', body: 'Write a status update for {{team}} about {{ topic }}. Mention {{team}} twice.' }) }); return [r.status, await r.json()]; });
  check('prompt saved', mk[0] === 200, JSON.stringify(mk[1]).slice(0, 120));
  await p.locator('#attachBtn').click();
  await p.waitForTimeout(400);
  const entry = p.locator('.plus-menu button', { hasText: 'Prompts' });
  check('Prompts entry is in the + menu', await entry.count() > 0);
  await p.screenshot({ path: `${out}/d-plusmenu.png` });
  if (await entry.count()) await entry.first().click(); else await p.evaluate(() => Snippets.open());
  await p.waitForSelector('.snip-item'); await p.screenshot({ path: `${out}/d-prompts.png` });
  check('title rendered as text, not HTML', await p.locator('.snip-item img').count() === 0 && dialogs === 0);
  await p.locator('.snip-item').first().click(); await p.waitForTimeout(400);
  const inputs = p.locator('textarea.snip-in');
  const nb = await inputs.count();
  check('one input per distinct blank', nb === 2, 'inputs=' + nb);
  if (nb >= 2) { await inputs.nth(0).fill('Sales'); await inputs.nth(1).fill('Q3 $& numbers'); }
  await p.screenshot({ path: `${out}/d-prompts-blanks.png` });
  await p.locator('button', { hasText: /^Use/ }).first().click(); await p.waitForTimeout(500);
  const val = await p.inputValue('#input');
  check('filled text landed in the message box, not sent', val === 'Write a status update for Sales about Q3 $& numbers. Mention Sales twice.', val);
  await p.fill('#input', '');

  // command box
  await p.keyboard.press('Control+k'); await p.waitForSelector('.pal-root [role="combobox"], .pal-input');
  await p.screenshot({ path: `${out}/d-palette.png` });
  const cmds = await p.locator('.pal-label').allInnerTexts();
  for (const want of ['Fork from latest reply', 'Export chat as Markdown', 'Export chat as JSON', 'Saved prompts', 'Instructions for this chat', 'See what the model saw'])
    check('command listed: ' + want, cmds.includes(want));
  await p.keyboard.type('export markdown'); await p.waitForTimeout(250);
  const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 15000 }), p.keyboard.press('Enter')]);
  const md = fs.readFileSync(await dl.path(), 'utf8');
  check('export from the command box downloads the whole chat', md.includes('Penang office launch') && md.includes('Draft a short checklist') && (md.match(/Here is a short plan/g) || []).length === 2, dl.suggestedFilename());
  await p.waitForTimeout(500);
  await p.keyboard.press('Control+k'); await p.waitForTimeout(300); await p.keyboard.type('fork'); await p.waitForTimeout(250); await p.keyboard.press('Enter');
  await p.waitForFunction(s => currentSession && currentSession !== s, sid1, { timeout: 15000 }); await p.waitForTimeout(1500);
  const sid2 = await p.evaluate(() => currentSession);
  const forkInfo = await p.evaluate(async ([a, b2]) => ({ orig: (await (await api('/api/messages?session_id=' + a)).json()).messages.length, copy: (await (await api('/api/messages?session_id=' + b2)).json()).messages.length, prefs: (await (await api('/api/chat/prefs?session_id=' + b2)).json()).instructions }), [sid1, sid2]);
  check('fork from the command box copies the chat', forkInfo.copy === 4 && forkInfo.orig === 4, JSON.stringify({ orig: forkInfo.orig, copy: forkInfo.copy }));
  check('fork carries the chat instructions', /INSTR-MARKER-123/.test(forkInfo.prefs || ''));
  await p.screenshot({ path: `${out}/d-fork.png` });

  // a different chat must not get the instructions
  await p.evaluate(() => newChat()); await p.waitForTimeout(1200);
  await send('Unrelated question about tea.');
  check('another chat does not get the instructions', !userText(lastReq()).includes('INSTR-MARKER-123'));
  await p.keyboard.press('Control+k'); await p.waitForTimeout(300); await p.keyboard.type('light'); await p.waitForTimeout(250); await p.keyboard.press('Enter'); await p.waitForTimeout(500);
  check('theme command changes the theme', await p.evaluate(() => document.body.classList.contains('theme-light')));
  await p.evaluate(s => openSession(s), sid1); await p.waitForTimeout(1500);
  await p.screenshot({ path: `${out}/d-chat-light.png` });
  check('no page errors on laptop', errs.length === 0, errs.join(' ; '));
  check('no script dialogs fired', dialogs === 0);
  await ctx.close();

  // phone
  const ph = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, hasTouch: true, isMobile: true });
  const q = await ph.newPage(); const perrs = [];
  q.on('pageerror', e => { const m = String(e); if (!/anonymous define/.test(m)) perrs.push(m.slice(0, 200)); });
  await q.addInitScript(s => localStorage.setItem('clipdrop_session', String(s)), sid1);
  await q.goto(BASE + '/', { waitUntil: 'domcontentloaded' }); await q.waitForTimeout(4000);
  const m = await q.evaluate(() => { const box = e => { const r = e.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; };
    return { sw: document.documentElement.scrollWidth, iw: innerWidth, main: box(document.getElementById('main')), placeholder: document.getElementById('input').placeholder, lens: [...document.querySelectorAll('#chat .msg.ai-msg .meta button')].slice(-4).map(e => e.textContent.trim() + ':' + box(e).slice(2).join('x')) }; });
  check('phone: no sideways scroll, main full width', m.sw === m.iw && m.main[2] === m.iw, JSON.stringify(m));
  check('phone: message box has a hint', !!m.placeholder, m.placeholder);
  await q.screenshot({ path: `${out}/p-chat.png` });
  await q.fill('#input', 'line one\nline two\nline three'); await q.waitForTimeout(500);
  const ov = await q.evaluate(() => { const a = document.getElementById('bugReportBtn'), s = document.getElementById('sendBtn'); if (!a || !s) return null; const x = a.getBoundingClientRect(), y = s.getBoundingClientRect(); return !(x.right <= y.left || x.left >= y.right || x.bottom <= y.top || x.top >= y.bottom); });
  check('phone: report button does not cover Send', ov === false, String(ov));
  await q.screenshot({ path: `${out}/p-composer.png` });
  await q.fill('#input', '');
  await q.evaluate(() => Snippets.open()); await q.waitForSelector('.snip-item'); await q.waitForTimeout(400); await q.screenshot({ path: `${out}/p-prompts.png` });
  await q.keyboard.press('Escape'); await q.waitForTimeout(300);
  await q.evaluate(() => ChatPrefs.open()); await q.waitForSelector('.cprefs-sheet.open'); await q.waitForTimeout(400); await q.screenshot({ path: `${out}/p-instructions.png` });
  await q.keyboard.press('Escape'); await q.waitForTimeout(300);
  await q.evaluate(() => Palette.open()); await q.waitForTimeout(500); await q.screenshot({ path: `${out}/p-palette.png` });
  check('phone: sheets add no sideways scroll', await q.evaluate(() => document.documentElement.scrollWidth === innerWidth));
  await q.keyboard.press('Escape');
  await q.evaluate(() => openSide()); await q.waitForTimeout(700); await q.screenshot({ path: `${out}/p-drawer.png` });
  check('no page errors on phone', perrs.length === 0, perrs.join(' ; '));
  await ph.close(); await b.close();
  console.log('\nRESULT', Object.values(R).filter(v => v === 'PASS').length, 'pass,', fail.length, 'fail');
  if (fail.length) { console.log(fail.join('\n')); process.exit(2); }
})().catch(e => { console.error('INTEG CRASHED', e.message.slice(0, 600)); process.exit(1); });
