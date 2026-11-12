/*
 * Saved prompts with fill-in blanks. A prompt can hold {{name}} blanks; using it
 * asks for each blank once and puts the finished text in the message box. It is
 * never sent automatically.
 *
 * Storage is on the host (GET/POST /api/snippets), so phones and laptop share it.
 * window.Snippets = { open(), parseBlanks(body), fill(body, values) }
 */
(function(root){
  'use strict';

  // --- pure functions (tested headlessly in tests/snippets.test.mjs) --------------
  // A blank is {{ name }}: braces around a name with no braces or line breaks in it.
  // An unclosed "{{" never matches, so it is left alone.
  var BLANK=/\{\{([^{}\n]*)\}\}/g;

  function parseBlanks(body){
    var names=[],seen=Object.create(null),m;
    BLANK.lastIndex=0;
    while((m=BLANK.exec(String(body==null?'':body)))){
      var n=m[1].trim();
      if(n&&!seen[n]){seen[n]=1;names.push(n)}
    }
    return names;
  }

  // Every blank is replaced. A name with no value becomes empty, so nothing that
  // looks like a blank is left in the finished text.
  function fill(body,values){
    values=values||{};
    return String(body==null?'':body).replace(BLANK,function(all,raw){
      var n=raw.trim();
      if(!n)return all;                       // "{{ }}" is not a blank
      var v=Object.prototype.hasOwnProperty.call(values,n)?values[n]:'';
      return v==null?'':String(v);
    });
  }

  var api={parseBlanks:parseBlanks,fill:fill};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof document==='undefined'||typeof window==='undefined')return;

  // --- UI -------------------------------------------------------------------------
  var el,scrim,sheet,titleEl,bodyEl,footEl,lastFocus=null;
  var items=[],loadError='',view='list',query='';

  function esc(s){
    if(typeof window.esc==='function')return window.esc(s==null?'':String(s));
    return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }
  function say(m){if(typeof window.toast==='function')window.toast(m)}

  function build(){
    if(el)return;
    el=document.createElement('div');
    el.className='snip-root';
    el.innerHTML=
      '<div class="snip-scrim" data-snip-close></div>'+
      '<section class="snip-sheet" role="dialog" aria-modal="true" aria-labelledby="snipTitle" tabindex="-1">'+
        '<div class="snip-grab" aria-hidden="true"></div>'+
        '<header class="snip-head"><h2 id="snipTitle">Prompts</h2>'+
        '<button type="button" class="snip-x" data-snip-close aria-label="Close">✕</button></header>'+
        '<div class="snip-body"></div>'+
        '<footer class="snip-foot"></footer>'+
      '</section>';
    document.body.appendChild(el);
    scrim=el.querySelector('.snip-scrim');
    sheet=el.querySelector('.snip-sheet');
    titleEl=el.querySelector('#snipTitle');
    bodyEl=el.querySelector('.snip-body');
    footEl=el.querySelector('.snip-foot');
    el.addEventListener('click',function(e){if(e.target.closest('[data-snip-close]'))close()});
    document.addEventListener('keydown',function(e){
      if(e.key==='Escape'&&sheet.classList.contains('open')){e.preventDefault();e.stopPropagation();close()}
    },true);
  }

  function close(){
    if(!sheet)return;
    scrim.classList.remove('open');sheet.classList.remove('open');
    if(lastFocus&&lastFocus.focus){try{lastFocus.focus({preventScroll:true})}catch(e){}}
  }

  async function call(path,payload){
    var r=await window.api(path,payload?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}:{});
    var j=null;try{j=await r.json()}catch(e){}
    if(!r.ok||!j||j.ok===false){
      throw new Error((j&&j.error)||('The host answered with status '+r.status+'.'));
    }
    return j;
  }

  async function load(){
    try{items=(await call('/api/snippets')).items||[];loadError=''}
    catch(e){items=[];loadError=e.message||'Could not load your prompts.'}
  }

  function setFoot(html){footEl.innerHTML=html}

  function renderList(){
    view='list';titleEl.textContent='Prompts';
    var q=query.trim().toLowerCase();
    var shown=items.filter(function(i){
      return !q||(i.title||'').toLowerCase().indexOf(q)>=0||(i.body||'').toLowerCase().indexOf(q)>=0;
    });
    var h='';
    if(loadError){
      h+='<div class="snip-note snip-err" role="alert">'+esc(loadError)+'</div>';
    }else if(!items.length){
      h+='<div class="snip-empty"><strong>No saved prompts yet</strong>'+
        '<p>Save a prompt you use often. Write {{name}} where something changes, and you will be asked to fill it in each time.</p></div>';
    }else{
      h+='<input type="search" class="snip-search" id="snipSearch" placeholder="Search prompts" aria-label="Search prompts" value="'+esc(query)+'">';
      if(!shown.length)h+='<div class="snip-empty"><p>Nothing matches that search.</p></div>';
      h+='<ul class="snip-list">';
      shown.forEach(function(i){
        var blanks=parseBlanks(i.body).length;
        h+='<li><button type="button" class="snip-item" data-use="'+esc(i.id)+'">'+
          '<span class="snip-t">'+esc(i.title)+'</span>'+
          '<span class="snip-p">'+esc((i.body||'').replace(/\s+/g,' ').slice(0,140))+'</span>'+
          (blanks?'<span class="snip-b">'+blanks+(blanks===1?' blank':' blanks')+' to fill</span>':'')+
          '</button><button type="button" class="snip-edit" data-edit="'+esc(i.id)+'" aria-label="Edit '+esc(i.title)+'">Edit</button></li>';
      });
      h+='</ul>';
    }
    bodyEl.innerHTML=h;
    setFoot('<button type="button" class="snip-btn primary" id="snipNew">New prompt</button>');
    var s=bodyEl.querySelector('#snipSearch');
    if(s)s.addEventListener('input',function(){
      query=s.value;var pos=s.selectionStart;renderList();
      var n=bodyEl.querySelector('#snipSearch');if(n){n.focus();try{n.setSelectionRange(pos,pos)}catch(e){}}
    });
    bodyEl.querySelectorAll('[data-use]').forEach(function(b){b.addEventListener('click',function(){choose(b.dataset.use)})});
    bodyEl.querySelectorAll('[data-edit]').forEach(function(b){b.addEventListener('click',function(){renderEdit(b.dataset.edit)})});
    footEl.querySelector('#snipNew').addEventListener('click',function(){renderEdit('')});
  }

  function byId(id){return items.filter(function(i){return i.id===id})[0]}

  function renderEdit(id){
    view='edit';
    var it=id?byId(id):null;
    titleEl.textContent=it?'Edit prompt':'New prompt';
    bodyEl.innerHTML=
      '<label class="snip-lab" for="snipT">Title</label>'+
      '<input class="snip-in" id="snipT" maxlength="80" autocomplete="off">'+
      '<label class="snip-lab" for="snipB">Prompt</label>'+
      '<textarea class="snip-in snip-ta" id="snipB" maxlength="8000" rows="8"></textarea>'+
      '<p class="snip-hint">Write {{name}} where something changes. You fill it in when you use the prompt.</p>'+
      '<div class="snip-note snip-err" id="snipErr" role="alert" hidden></div>';
    bodyEl.querySelector('#snipT').value=it?it.title:'';
    bodyEl.querySelector('#snipB').value=it?it.body:'';
    setFoot((it?'<button type="button" class="snip-btn danger" id="snipDel">Delete</button>':'')+
      '<button type="button" class="snip-btn" id="snipBack">Cancel</button>'+
      '<button type="button" class="snip-btn primary" id="snipSave">Save</button>');
    bodyEl.querySelector('#snipT').focus();
    footEl.querySelector('#snipBack').addEventListener('click',renderList);
    footEl.querySelector('#snipSave').addEventListener('click',function(){saveEdit(it)});
    var d=footEl.querySelector('#snipDel');
    if(d)d.addEventListener('click',function(){confirmDelete(it)});
  }

  async function saveEdit(it){
    var err=bodyEl.querySelector('#snipErr'),btn=footEl.querySelector('#snipSave');
    var payload={title:bodyEl.querySelector('#snipT').value,body:bodyEl.querySelector('#snipB').value};
    if(it)payload.id=it.id;
    btn.disabled=true;
    try{await call('/api/snippets',payload)}
    catch(e){err.textContent=e.message;err.hidden=false;btn.disabled=false;return}
    await load();renderList();say('Prompt saved');
  }

  function confirmDelete(it){
    view='confirm';titleEl.textContent='Delete prompt';
    bodyEl.innerHTML='<div class="snip-empty"><strong>Delete “'+esc(it.title)+'”?</strong><p>This cannot be undone.</p></div>'+
      '<div class="snip-note snip-err" id="snipErr" role="alert" hidden></div>';
    setFoot('<button type="button" class="snip-btn" id="snipNo">Keep it</button>'+
      '<button type="button" class="snip-btn danger" id="snipYes">Delete</button>');
    footEl.querySelector('#snipNo').addEventListener('click',function(){renderEdit(it.id)});
    footEl.querySelector('#snipYes').addEventListener('click',async function(){
      try{await call('/api/snippets/delete',{id:it.id})}
      catch(e){var er=bodyEl.querySelector('#snipErr');er.textContent=e.message;er.hidden=false;return}
      await load();renderList();say('Prompt deleted');
    });
  }

  function choose(id){
    var it=byId(id);if(!it)return;
    var names=parseBlanks(it.body);
    if(!names.length){insert(it.body);return}
    view='fill';titleEl.textContent=it.title;
    bodyEl.innerHTML='<p class="snip-hint">Fill in the blanks. The finished text goes in your message box. Nothing is sent.</p>'+
      names.map(function(n,i){
        return '<label class="snip-lab" for="snipF'+i+'">'+esc(n)+'</label>'+
          '<textarea class="snip-in" id="snipF'+i+'" data-name="'+esc(n)+'" rows="2"></textarea>';
      }).join('');
    setFoot('<button type="button" class="snip-btn" id="snipBack">Back</button>'+
      '<button type="button" class="snip-btn primary" id="snipUse">Use</button>');
    footEl.querySelector('#snipBack').addEventListener('click',renderList);
    footEl.querySelector('#snipUse').addEventListener('click',function(){
      var v=Object.create(null);
      bodyEl.querySelectorAll('[data-name]').forEach(function(t){v[t.dataset.name]=t.value});
      insert(fill(it.body,v));
    });
    var first=bodyEl.querySelector('textarea');if(first)first.focus();
  }

  function insert(text){
    var box=document.getElementById('input');
    if(!box){say('The message box was not found.');return}
    var cur=box.value||'';
    box.value=cur.trim()?cur.replace(/\s+$/,'')+'\n\n'+text:text;
    box.dispatchEvent(new Event('input',{bubbles:true}));
    close();
    box.focus();
  }

  async function open(){
    build();
    lastFocus=document.activeElement;
    query='';
    scrim.classList.add('open');sheet.classList.add('open');
    bodyEl.innerHTML='<div class="snip-empty"><p>Loading…</p></div>';setFoot('');
    sheet.focus({preventScroll:true});
    await load();
    renderList();
  }

  // The composer's + menu is built by the page; add one entry near the front of it.
  function addMenuEntry(){
    var menu=document.getElementById('plusMenu');
    if(!menu||menu.querySelector('[data-snip]'))return;
    var b=document.createElement('button');
    b.type='button';b.setAttribute('role','menuitem');b.setAttribute('data-snip','1');
    b.innerHTML='<span class="pm-ico">📋</span> Prompts';
    b.addEventListener('click',function(){
      if(typeof window.closePlusMenu==='function')window.closePlusMenu();
      open();
    });
    // Second slot: the menu is a pill row that scrolls on a phone, so the last slot is hidden.
    menu.insertBefore(b,menu.children[1]||null);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',addMenuEntry);
  else addMenuEntry();

  api.open=open;
  window.Snippets=api;
})(typeof window!=='undefined'?window:globalThis);
