/*
 * Chat instructions: standing text for ONE chat, sent with every turn of that chat.
 *
 * Reads and writes /api/chat/prefs. The server is the only source of truth: this file
 * never decides what the model receives. The prompt panel (promptlens.js) shows the
 * block as "Chat instructions", so what is set here can always be checked there.
 *
 * window.ChatPrefs = { open() }
 */
(function(){
  'use strict';

  var LIMIT=4000;
  var btn=null,root,scrim,sheet,box,countEl,msgEl,saveBtn,clearBtn,subEl,lastFocus=null;
  var saved='',loadedFor=0,loadFailed=false,busy=false,refreshTimer=0;

  function sid(){try{return Number(currentSession)||0}catch(e){return 0}}
  function say(m){if(typeof window.toast==='function')window.toast(m)}
  function num(n){return Number(n||0).toLocaleString('en-US')}

  async function call(method,body){
    var id=sid();
    var r=await window.api(method==='GET'?'/api/chat/prefs?session_id='+id:'/api/chat/prefs',
      method==='GET'?{}:{method:'POST',body:JSON.stringify(body)});
    var j=null;try{j=await r.json()}catch(e){}
    return {ok:r.status===200&&!!j&&!!j.ok,status:r.status,body:j||{}};
  }

  // --- the control next to the composer ---------------------------------------------
  function paint(){
    if(!btn)return;
    var on=!!saved;
    btn.classList.toggle('on',on);
    btn.classList.toggle('unknown',loadFailed);
    btn.setAttribute('aria-pressed',on?'true':'false');
    btn.title=loadFailed?'Could not check this chat\'s instructions. Tap to try again.'
      :on?'This chat has its own instructions. Tap to view or change them.':'Give this chat its own instructions';
    btn.setAttribute('aria-label',btn.title);
    btn.querySelector('.cprefs-label').textContent=loadFailed?'Instructions ?':on?'Instructions on':'Instructions';
  }
  function ensureButton(){
    if(btn)return btn;
    var anchor=document.getElementById('modelDd');
    if(!anchor||!anchor.parentNode)return null;
    btn=document.createElement('button');
    btn.type='button';
    btn.className='cprefs-btn';
    btn.innerHTML='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/></svg>'+
      '<span class="cprefs-label">Instructions</span><i class="cprefs-dot" aria-hidden="true"></i>';
    btn.addEventListener('click',function(){open()});
    anchor.parentNode.insertBefore(btn,anchor);
    paint();
    return btn;
  }
  async function refresh(){
    ensureButton();
    var id=sid();
    if(id===loadedFor)return;
    loadedFor=id;
    saved='';loadFailed=false;paint();
    if(!id)return;
    try{
      var res=await call('GET');
      if(id!==sid())return;                      // the chat changed while this was loading
      if(res.ok){saved=String(res.body.instructions||'');LIMIT=res.body.limit||LIMIT}
      else loadFailed=true;
    }catch(e){loadFailed=true}
    // "Off" and "could not find out" are different answers. Forget the chat so the
    // next refresh asks again instead of trusting a failed read.
    if(loadFailed)loadedFor=null;
    paint();
  }

  // --- the sheet ---------------------------------------------------------------------
  function build(){
    if(root)return;
    root=document.createElement('div');
    root.className='cprefs-root';
    root.innerHTML=
      '<div class="cprefs-scrim" data-cprefs-close></div>'+
      '<section class="cprefs-sheet" role="dialog" aria-modal="true" aria-labelledby="cprefsTitle" tabindex="-1">'+
        '<div class="cprefs-grab" aria-hidden="true"></div>'+
        '<header class="cprefs-head"><div><h2 id="cprefsTitle">Instructions for this chat</h2>'+
        '<p class="cprefs-sub" id="cprefsSub"></p></div>'+
        '<button type="button" class="cprefs-x" data-cprefs-close aria-label="Close">✕</button></header>'+
        '<div class="cprefs-body">'+
          '<label class="cprefs-lab" for="cprefsBox">Instructions</label>'+
          '<textarea id="cprefsBox" class="cprefs-box" rows="7" placeholder="For example: Answer in Malay. Or: You are reviewing a contract, be strict."></textarea>'+
          '<div class="cprefs-meta"><span id="cprefsMsg" class="cprefs-msg" role="status" aria-live="polite"></span><span id="cprefsCount" class="cprefs-count"></span></div>'+
        '</div>'+
        '<footer class="cprefs-foot">'+
          '<button type="button" class="cprefs-act" id="cprefsClear">Clear</button>'+
          '<button type="button" class="cprefs-act primary" id="cprefsSave">Save</button>'+
        '</footer>'+
      '</section>';
    document.body.appendChild(root);
    scrim=root.querySelector('.cprefs-scrim');
    sheet=root.querySelector('.cprefs-sheet');
    box=root.querySelector('#cprefsBox');
    countEl=root.querySelector('#cprefsCount');
    msgEl=root.querySelector('#cprefsMsg');
    saveBtn=root.querySelector('#cprefsSave');
    clearBtn=root.querySelector('#cprefsClear');
    subEl=root.querySelector('#cprefsSub');
    root.addEventListener('click',function(e){if(e.target.closest('[data-cprefs-close]'))close()});
    box.addEventListener('input',update);
    saveBtn.addEventListener('click',function(){save(box.value)});
    clearBtn.addEventListener('click',function(){box.value='';update();save('')});
    document.addEventListener('keydown',function(e){
      if(e.key==='Escape'&&sheet.classList.contains('open')){e.preventDefault();e.stopPropagation();close()}
    },true);
  }

  function setMsg(text,bad){msgEl.textContent=text||'';msgEl.classList.toggle('bad',!!bad)}
  function update(){
    var n=box.value.trim().length,over=n>LIMIT;
    countEl.textContent=num(n)+' / '+num(LIMIT);
    countEl.classList.toggle('bad',over);
    if(over)setMsg('Too long by '+num(n-LIMIT)+(n-LIMIT===1?' character':' characters')+'. Shorten it to save.',true);
    else if(msgEl.classList.contains('bad')&&!busy)setMsg('');
    var none=!sid();
    saveBtn.disabled=busy||none||over||box.value.trim()===saved;
    clearBtn.disabled=busy||none||(!saved&&!box.value);
  }

  async function open(){
    build();
    lastFocus=document.activeElement;
    scrim.classList.add('open');sheet.classList.add('open');
    var id=sid();
    setMsg('');
    if(!id){
      box.value='';box.disabled=true;
      subEl.textContent='This chat has not been started yet. Send a message first, then come back and add instructions.';
      update();
      sheet.focus({preventScroll:true});
      return;
    }
    box.disabled=false;
    subEl.textContent='Sent with every message in this chat, and nowhere else.';
    box.value=saved;update();
    sheet.focus({preventScroll:true});
    try{
      var res=await call('GET');
      if(id!==sid())return;
      if(res.ok){
        saved=String(res.body.instructions||'');LIMIT=res.body.limit||LIMIT;
        if(box.value.trim()===''||document.activeElement!==box)box.value=saved;
        paint();update();
      }else setMsg((res.body&&res.body.error)||'Could not load the saved instructions.',true);
    }catch(e){setMsg('Could not reach AirGPT. Saved instructions may be out of date.',true)}
    if(!('ontouchstart' in window))box.focus({preventScroll:true});
  }
  function close(){
    if(!sheet)return;
    scrim.classList.remove('open');sheet.classList.remove('open');
    if(lastFocus&&lastFocus.focus){try{lastFocus.focus({preventScroll:true})}catch(e){}}
  }

  async function save(text){
    if(busy||!sid())return;
    busy=true;update();setMsg('Saving…');
    try{
      var res=await call('POST',{session_id:sid(),instructions:text});
      if(res.ok){
        saved=String(res.body.instructions||'');
        box.value=saved;
        paint();
        busy=false;update();
        close();
        say(saved?'Instructions saved for this chat':'Instructions cleared');
        return;
      }
      setMsg((res.body&&res.body.error)||('Could not save. The host answered with status '+res.status+'.'),true);
    }catch(e){setMsg('Could not reach AirGPT. Nothing was saved.',true)}
    busy=false;update();
  }

  function start(){
    ensureButton();
    var chat=document.getElementById('chat');
    if(chat)new MutationObserver(function(){
      clearTimeout(refreshTimer);
      refreshTimer=setTimeout(refresh,300);
    }).observe(chat,{childList:true});
    setTimeout(refresh,800);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);
  else start();

  window.ChatPrefs={open:open};
})();
