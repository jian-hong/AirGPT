/*
 * Command palette: Ctrl+K (Cmd+K on a Mac) opens a search box for things you can do.
 *
 * Every command calls a function that already exists in the page. A command whose
 * function is missing at run time is not listed. Optional modules are detected when
 * the palette opens:
 *   window.ChatTools  forkLatest(), exportMarkdown(), exportJSON()
 *   window.Snippets   open()
 *   window.ChatPrefs  open()
 *
 * window.Palette = { open(), close(), toggle(), showShortcuts(), rank(query, items) }
 * rank() is pure and is also exported through module.exports for tests.
 */
(function(root,factory){
  var api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(typeof window!=='undefined'&&root===window)api.install();
})(typeof window!=='undefined'?window:this,function(){
  'use strict';

  /* ---------- matcher (pure) ---------- */
  function norm(s){return String(s==null?'':s).toLowerCase()}
  // Score one string against a query. 0 means no match. Higher is better:
  // prefix > word start > plain substring > letters in order but scattered.
  function scoreText(q,text){
    var t=norm(text);
    if(!q)return 1;
    if(!t)return 0;
    if(t.indexOf(q)===0)return 1000-Math.min(t.length,200)/10;
    var words=t.split(/[\s\-_\/.:]+/),i;
    for(i=0;i<words.length;i++){
      if(words[i].indexOf(q)===0)return 700-i*5-Math.min(t.length,200)/10;
    }
    // every query word starts a word, in order ("sw th" -> "switch theme")
    var qw=q.split(/\s+/).filter(Boolean);
    if(qw.length>1){
      var wi=0,ok=true;
      for(i=0;i<qw.length;i++){
        while(wi<words.length&&words[wi].indexOf(qw[i])!==0)wi++;
        if(wi>=words.length){ok=false;break}
        wi++;
      }
      if(ok)return 600-Math.min(t.length,200)/10;
    }
    var at=t.indexOf(q);
    if(at>0)return 400-at/2-Math.min(t.length,200)/20;
    // scattered letters, in order
    var qi=0,first=-1,last=-1;
    for(i=0;i<t.length&&qi<q.length;i++){
      if(t.charAt(i)===q.charAt(qi)){if(first<0)first=i;last=i;qi++}
    }
    if(qi<q.length)return 0;
    return 200*(q.length/(last-first+1))+10-first/20;
  }
  // items: [{label, keywords?, ...}]. Returns matches best first. Ties keep input order.
  function rank(query,items){
    var q=norm(query).trim();
    items=items||[];
    if(!q)return items.slice();
    var out=[];
    for(var i=0;i<items.length;i++){
      var it=items[i];
      var s=scoreText(q,it.label);
      if(it.keywords){
        var k=scoreText(q,it.keywords)*0.6;
        if(k>s)s=k;
      }
      if(s>0)out.push({it:it,s:s,i:i});
    }
    out.sort(function(a,b){return b.s-a.s||a.i-b.i});
    return out.map(function(x){return x.it});
  }

  function install(){
    var doc=document;
    var isMac=/Mac|iPhone|iPad/i.test(navigator.platform||navigator.userAgent||'');
    var MOD=isMac?'⌘':'Ctrl';
    var THEMES=[['glass','Liquid Glass'],['classyblack','Classy Black'],['light','Light'],['dark','Dark flat']];

    var rootEl,panel,input,list,status,backBtn,titleEl;
    var isOpen=false,mode='commands',lastFocus=null,shown=[],active=0,chats=[],chatsState='idle',chatsSeq=0;

    function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
    function say(m){try{if(typeof window.toast==='function')window.toast(m)}catch(e){}}
    function fn(name){try{return typeof window[name]==='function'?window[name]:null}catch(e){return null}}
    function sub(obj,names){
      if(!obj)return null;
      for(var i=0;i<names.length;i++)if(typeof obj[names[i]]==='function')return obj[names[i]].bind(obj);
      return null;
    }
    function bodyHas(c){return doc.body.classList.contains(c)}
    function curTheme(){
      var b=doc.body.classList;
      return b.contains('theme-light')?'light':b.contains('theme-classyblack')?'classyblack':b.contains('theme-dark')?'dark':'glass';
    }
    function thinkingUsable(){
      var f=fn('thinkingAllowed');
      if(!f)return true;
      try{return !!f()}catch(e){return true}
    }
    function thinkingOn(){try{return !!thinkingEnabled}catch(e){return true}}

    /* ---------- commands ---------- */
    function commands(){
      var out=[];
      function add(label,keywords,run,hint){out.push({kind:'command',label:label,keywords:keywords||'',run:run,hint:hint||''})}
      // Look the page function up again when the command runs, so each command calls its own.
      function call(name){var a=Array.prototype.slice.call(arguments,1);return function(){var g=fn(name);if(!g)throw new Error('This is not available right now.');return g.apply(null,a)}}
      if(fn('newChat'))add('New chat','start fresh conversation compose',call('newChat'));
      if(fn('openSearchModal'))add('Search chats','find history messages',call('openSearchModal'));
      if(fn('openSettings'))add('Open settings','preferences options connect devices keys',call('openSettings'));
      if(fn('applyTheme')){
        THEMES.forEach(function(t){
          if(t[0]===curTheme())return;
          add('Switch theme: '+t[1],'appearance dark light colors look',call('applyTheme',t[0]));
        });
      }
      if(fn('toggleSideCollapsed'))add('Show or hide the sidebar','left panel menu collapse expand',call('toggleSideCollapsed'));
      if(fn('showWorkspace')){
        add('Go to Home','chats workspace main',call('showWorkspace','home'));
        add('Go to Cortex workspace','agent agents cortex',call('showWorkspace','cortex'));
      }
      if(fn('setModelTier')){
        [['basic','Basic'],['high','High'],['max','Max']].forEach(function(t){
          add('Effort: '+t[1],'model tier quality speed reasoning',call('setModelTier',t[0]));
        });
      }
      if(fn('toggleThinking')&&thinkingUsable()){
        add(thinkingOn()?'Thinking: turn off':'Thinking: turn on','reasoning think deep',call('toggleThinking'));
      }
      if(window.PromptLens&&typeof window.PromptLens.openLatest==='function'){
        add('See what the model saw','prompt lens tokens context latest reply',function(){return window.PromptLens.openLatest()});
      }
      var CT=window.ChatTools,s;
      if((s=sub(CT,['forkLatest'])))add('Fork from latest reply','branch copy split chat',s);
      if((s=sub(CT,['exportMarkdown'])))add('Export chat as Markdown','download save md',s);
      if((s=sub(CT,['exportJSON'])))add('Export chat as JSON','download save data',s);
      if((s=sub(window.Snippets,['open'])))add('Saved prompts','snippets templates reuse',s);
      if((s=sub(window.ChatPrefs,['open'])))add('Instructions for this chat','custom tone rules prefs',s);
      add('Keyboard shortcuts','keys help hotkeys ?',function(){showShortcuts()},'?');
      return out;
    }

    // Only keys that the page's own keydown handlers really implement.
    var SHORTCUTS=[
      [MOD+' K','Open this command box'],
      ['?','Show this list (when you are not typing)'],
      ['Enter','Send your message'],
      ['Shift Enter','New line in your message'],
      [MOD+' U','Attach a file'],
      ['Ctrl Shift Space','Jump to the message box'],
      ['Esc','Close the open panel or dialog']
    ];

    /* ---------- chats (same endpoint the sidebar uses) ---------- */
    function loadChats(){
      var my=++chatsSeq;
      var f=fn('api');
      if(!f){chatsState='error';return Promise.resolve()}
      chatsState='loading';
      return f('/api/sessions').then(function(r){
        if(!r.ok)throw new Error('status '+r.status);
        return r.json();
      }).then(function(d){
        if(my!==chatsSeq)return;
        chats=(d&&d.sessions||[]).filter(function(s){return s&&s.id&&(s.msg_count||0)>0}).map(function(s){
          return {kind:'chat',id:s.id,label:String(s.title||('Chat #'+s.id)),keywords:'',hint:'Chat'};
        });
        chatsState='ok';
      }).catch(function(){
        if(my!==chatsSeq)return;
        chats=[];chatsState='error';
      }).then(function(){if(isOpen&&mode==='commands')render()});
    }

    /* ---------- dialog ---------- */
    function build(){
      if(rootEl)return;
      rootEl=doc.createElement('div');
      rootEl.className='pal-root';
      rootEl.innerHTML=
        '<div class="pal-scrim" data-pal-close></div>'+
        '<div class="pal-panel" role="dialog" aria-modal="true" aria-labelledby="palTitle" tabindex="-1">'+
          '<div class="pal-head">'+
            '<h2 id="palTitle" class="pal-title">Command box</h2>'+
            '<button type="button" class="pal-back" id="palBack" hidden>All commands</button>'+
            '<button type="button" class="pal-x" data-pal-close aria-label="Close">✕</button>'+
          '</div>'+
          '<input id="palInput" class="pal-input" type="text" role="combobox" aria-expanded="true" aria-controls="palList" aria-autocomplete="list" aria-label="Type a command or a chat name" placeholder="Type a command or a chat name" autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="go">'+
          '<div class="pal-status" id="palStatus" role="status" aria-live="polite"></div>'+
          '<ul class="pal-list" id="palList" role="listbox" aria-label="Commands"></ul>'+
          '<div class="pal-foot" aria-hidden="true"><span>↑↓ move</span><span class="pal-foot-run">Enter run</span><span>Esc close</span></div>'+
        '</div>';
      doc.body.appendChild(rootEl);
      panel=rootEl.querySelector('.pal-panel');
      input=rootEl.querySelector('#palInput');
      list=rootEl.querySelector('#palList');
      status=rootEl.querySelector('#palStatus');
      backBtn=rootEl.querySelector('#palBack');
      titleEl=rootEl.querySelector('#palTitle');
      rootEl.addEventListener('click',function(e){
        if(e.target.closest('[data-pal-close]'))close();
      });
      backBtn.addEventListener('click',function(){mode='commands';input.value='';active=0;render();input.focus()});
      input.addEventListener('input',function(){active=0;render()});
      list.addEventListener('click',function(e){
        var li=e.target.closest('[data-i]');
        if(li)run(+li.dataset.i);
      });
      list.addEventListener('pointermove',function(e){
        var li=e.target.closest('[data-i]');
        if(li&&mode==='commands'&&+li.dataset.i!==active){active=+li.dataset.i;mark()}
      });
      panel.addEventListener('keydown',onPanelKey);
    }

    function visibleItems(){
      var q=input.value;
      if(mode==='shortcuts'){
        return rank(q,SHORTCUTS.map(function(s){return {kind:'key',label:s[1],keys:s[0]}}));
      }
      var cmds=commands();
      if(!q.trim())return cmds.concat(chats.slice(0,8));
      return rank(q,cmds.concat(chats)).slice(0,50);
    }

    function render(){
      shown=visibleItems();
      if(active>=shown.length)active=Math.max(0,shown.length-1);
      list.textContent='';
      var isKeys=mode==='shortcuts';
      list.setAttribute('role',isKeys?'list':'listbox');
      list.setAttribute('aria-label',isKeys?'Keyboard shortcuts':'Commands');
      input.setAttribute('role',isKeys?'searchbox':'combobox');
      if(isKeys){input.removeAttribute('aria-controls');input.removeAttribute('aria-expanded');input.removeAttribute('aria-activedescendant')}
      else{input.setAttribute('aria-controls','palList');input.setAttribute('aria-expanded','true')}
      titleEl.textContent=isKeys?'Keyboard shortcuts':'Command box';
      backBtn.hidden=!isKeys;
      var runHint=rootEl.querySelector('.pal-foot-run');if(runHint)runHint.hidden=isKeys;   // Enter does nothing in the key list
      input.placeholder=isKeys?'Filter shortcuts':'Type a command or a chat name';
      input.setAttribute('aria-label',input.placeholder);
      shown.forEach(function(it,i){
        var li=doc.createElement('li');
        li.dataset.i=i;
        var lab=doc.createElement('span');lab.className='pal-label';lab.textContent=it.label;
        if(isKeys){
          li.className='pal-item pal-key';
          li.setAttribute('role','listitem');
          var kk=doc.createElement('span');kk.className='pal-keys';
          it.keys.split(' ').forEach(function(k){var kb=doc.createElement('kbd');kb.textContent=k;kk.appendChild(kb)});
          li.appendChild(lab);li.appendChild(kk);
        }else{
          li.id='palOpt'+i;
          li.className='pal-item'+(it.kind==='chat'?' pal-chat':'');
          li.setAttribute('role','option');
          li.appendChild(lab);
          if(it.hint){var hs=doc.createElement('span');hs.className='pal-hint';hs.textContent=it.hint;li.appendChild(hs)}
        }
        list.appendChild(li);
      });
      var msg='';
      if(!shown.length)msg=input.value.trim()?'Nothing matches "'+input.value.trim()+'".':'Nothing to show.';
      else if(mode==='commands'){
        if(chatsState==='error')msg='Could not load your chats. Commands still work.';
        else if(chatsState==='loading'&&!chats.length)msg='Loading your chats…';
      }
      status.textContent=msg;
      status.hidden=!msg;
      mark();
    }

    function mark(){
      if(mode==='shortcuts')return;
      var els=list.children;
      for(var i=0;i<els.length;i++){
        var on=i===active;
        els[i].classList.toggle('active',on);
        els[i].setAttribute('aria-selected',on?'true':'false');
      }
      if(shown.length){
        input.setAttribute('aria-activedescendant','palOpt'+active);
        var a=els[active];
        if(a&&a.scrollIntoView)a.scrollIntoView({block:'nearest'});
      }else input.removeAttribute('aria-activedescendant');
    }

    function move(d){
      if(!shown.length||mode==='shortcuts')return;
      active=(active+d+shown.length)%shown.length;
      mark();
    }

    function fail(label){
      return function(e){
        try{console.warn('[Palette]',label,e)}catch(x){}
        say('"'+label+'" did not work. '+((e&&e.message)?e.message:'Try again.'));
      };
    }
    function run(i){
      var it=shown[i];
      if(!it||it.kind==='key')return;
      if(it.kind==='command'&&it.label==='Keyboard shortcuts'){showShortcuts();return}
      close();
      // Let focus settle back first so a command that moves focus wins.
      setTimeout(function(){
        try{
          var r;
          if(it.kind==='chat'){
            var f=fn('openSession');
            if(!f){say('Could not open that chat.');return}
            r=f(it.id);
          }else r=it.run();
          if(r&&typeof r.then==='function')r.then(null,fail(it.label));
        }catch(e){fail(it.label)(e)}
      },0);
    }

    function focusables(){
      return Array.prototype.filter.call(panel.querySelectorAll('input,button'),function(el){
        return !el.hidden&&!el.disabled&&el.offsetParent!==null;
      });
    }
    function onPanelKey(e){
      if(e.key==='ArrowDown'){e.preventDefault();move(1)}
      else if(e.key==='ArrowUp'){e.preventDefault();move(-1)}
      else if(e.key==='Enter'&&e.target===input){e.preventDefault();if(!e.isComposing)run(active)}
      else if(e.key==='Backspace'&&mode==='shortcuts'&&!input.value){e.preventDefault();backBtn.click()}
      else if(e.key==='Tab'){
        var f=focusables();
        if(!f.length){e.preventDefault();return}
        var first=f[0],last=f[f.length-1];
        if(e.shiftKey&&(doc.activeElement===first||doc.activeElement===panel)){e.preventDefault();last.focus()}
        else if(!e.shiftKey&&doc.activeElement===last){e.preventDefault();first.focus()}
      }
    }

    function open(startMode){
      build();
      if(isOpen){
        if(startMode&&startMode!==mode){mode=startMode;input.value='';active=0;render()}
        return;
      }
      lastFocus=doc.activeElement;
      mode=startMode||'commands';
      input.value='';active=0;
      isOpen=true;
      rootEl.classList.add('open');
      render();
      if(mode==='commands')loadChats();
      input.focus({preventScroll:true});
    }
    function close(){
      if(!isOpen)return;
      isOpen=false;chatsSeq++;
      rootEl.classList.remove('open');
      var lf=lastFocus;lastFocus=null;
      if(lf&&lf.focus&&doc.contains(lf)){try{lf.focus({preventScroll:true})}catch(e){}}
    }
    function toggle(){isOpen?close():open()}
    function showShortcuts(){
      if(!isOpen){open('shortcuts');return}
      mode='shortcuts';input.value='';active=0;render();input.focus();
    }

    /* ---------- global keys ---------- */
    function otherDialogOpen(){
      var els=doc.querySelectorAll('.modal.open,.project-pick-modal,.rag-pending-modal,.plens-sheet.open,[aria-modal="true"]');
      for(var i=0;i<els.length;i++){
        var el=els[i];
        if(rootEl&&rootEl.contains(el))continue;
        var cs=getComputedStyle(el);
        if(cs.display==='none'||cs.visibility==='hidden')continue;
        if(el.classList.contains('plens-sheet')&&!el.classList.contains('open'))continue;
        return true;
      }
      return false;
    }
    function inTextField(t){
      if(!t||!t.tagName)return false;
      var n=t.tagName;
      return n==='INPUT'||n==='TEXTAREA'||n==='SELECT'||!!t.isContentEditable;
    }
    doc.addEventListener('keydown',function(e){
      var k=e.key||'';
      if((e.ctrlKey||e.metaKey)&&!e.altKey&&!e.shiftKey&&k.toLowerCase()==='k'){
        if(isOpen){e.preventDefault();e.stopPropagation();close();return}
        if(bodyHas('openide-mode')||otherDialogOpen())return;
        e.preventDefault();e.stopPropagation();open();return;
      }
      if(isOpen&&k==='Escape'){e.preventDefault();e.stopPropagation();close();return}
      if(k==='?'&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&!isOpen&&!inTextField(e.target)){
        if(bodyHas('openide-mode')||otherDialogOpen())return;
        e.preventDefault();open('shortcuts');
      }
    },true);

    /* ---------- top bar hint (wide screens only; CSS hides it on phones) ---------- */
    function addHint(){
      var anchor=doc.getElementById('settingsBtn');
      if(!anchor||!anchor.parentNode||doc.getElementById('palHint'))return;
      var b=doc.createElement('button');
      b.type='button';b.id='palHint';b.className='pal-hint-btn';
      b.title='Open the command box ('+MOD+' K)';
      b.setAttribute('aria-label','Open the command box');
      b.setAttribute('aria-keyshortcuts',(isMac?'Meta':'Control')+'+K');
      b.innerHTML='<kbd>'+esc(MOD)+'</kbd><kbd>K</kbd>';
      b.addEventListener('click',function(){open()});
      anchor.parentNode.insertBefore(b,anchor);
    }
    /* A phone has no Ctrl+K and the top bar has no room for the hint, so the command
       box would be unreachable there. The composer's + menu is on every screen size. */
    function addMenuEntry(){
      var menu=doc.getElementById('plusMenu');
      if(!menu||menu.querySelector('[data-pal]'))return;
      var b=doc.createElement('button');
      b.type='button';b.setAttribute('role','menuitem');b.setAttribute('data-pal','1');
      var ico=doc.createElement('span');ico.className='pm-ico';ico.textContent='\u2318';
      b.appendChild(ico);b.appendChild(doc.createTextNode(' Commands'));
      b.addEventListener('click',function(){
        if(typeof window.closePlusMenu==='function')window.closePlusMenu();
        open();
      });
      menu.insertBefore(b,menu.children[2]||null);
    }
    function addEntryPoints(){addHint();addMenuEntry()}
    if(doc.readyState==='loading')doc.addEventListener('DOMContentLoaded',addEntryPoints);
    else addEntryPoints();

    window.Palette={open:function(){open()},close:close,toggle:toggle,showShortcuts:showShortcuts,rank:rank};
  }

  return {rank:rank,scoreText:scoreText,install:install};
});
