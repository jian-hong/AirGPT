/*
 * Chat tools: fork a chat from one reply, and export the whole chat.
 *
 * Both talk to the server (POST /api/sessions/fork, GET /api/sessions/export).
 * The server copies and exports from the database, so nothing here depends on what
 * happens to be rendered.
 *
 * window.ChatTools = { fork(messageId), exportChat(format) }
 */
(function(){
  'use strict';

  function say(msg){try{toast(msg)}catch(e){console.log(msg)}}
  function curSid(){try{return Number(currentSession)||0}catch(e){return 0}}
  function errText(r,fallback){
    return r.json().then(function(j){return (j&&j.error)||fallback},function(){return fallback});
  }

  var forking=false;
  function fork(messageId){
    var mid=Number(messageId)||0,sid=0;
    try{var m=msgById(mid);if(m&&m.session_id)sid=Number(m.session_id)}catch(e){}
    if(!sid)sid=curSid();
    if(!mid||!sid){say('Could not fork: no chat is open.');return Promise.resolve(null)}
    if(window.AirUI&&window.AirUI.shareAcl()){say('A shared chat cannot be forked.');return Promise.resolve(null)}
    if(forking)return Promise.resolve(null);
    forking=true;
    return api('/api/sessions/fork',{method:'POST',body:JSON.stringify({session_id:sid,upto_message_id:mid})})
      .then(function(r){
        if(!r.ok)return errText(r,'Could not fork this chat.').then(function(t){say(t);return null});
        return r.json().then(function(d){
          var s=d.session;
          say('Forked. You are now in the copy.');
          try{pullHistory()}catch(e){}
          /* openSession treats an id missing from the chat list as deleted, so refresh the list first. */
          var refresh=Promise.resolve();
          try{refresh=Promise.resolve(loadVaultTree())}catch(e){}
          return refresh.catch(function(){}).then(function(){return openSession(s.id)}).then(function(){return s});
        });
      })
      .catch(function(e){if(!e||e.message!=='auth')say('Could not fork this chat. Check your connection.');return null})
      .then(function(v){forking=false;return v});
  }

  function exportChat(format){
    var sid=curSid(),fmt=format==='json'?'json':'md';
    if(!sid){say('Open a chat first.');return Promise.resolve(false)}
    return api('/api/sessions/export?session_id='+sid+'&format='+fmt)
      .then(function(r){
        if(!r.ok)return errText(r,'Could not export this chat.').then(function(t){say(t);return false});
        var cd=r.headers.get('Content-Disposition')||'',mt=/filename="([^"]+)"/.exec(cd);
        var name=mt?mt[1]:'airgpt-chat.'+fmt;
        return r.blob().then(function(b){
          var a=document.createElement('a');
          a.href=URL.createObjectURL(b);a.download=name;
          document.body.appendChild(a);a.click();a.remove();
          setTimeout(function(){URL.revokeObjectURL(a.href)},2000);
          say('Chat saved as '+(fmt==='json'?'JSON':'Markdown')+'.');
          return true;
        });
      })
      .catch(function(e){if(!e||e.message!=='auth')say('Could not export this chat. Check your connection.');return false});
  }

  /* Fork from the newest reply on screen. Used by the command box. */
  function forkLatest(){
    var nodes=document.querySelectorAll('#chat .msg.ai-msg[id^="msg-"]');
    var mid=nodes.length?Number(nodes[nodes.length-1].id.slice(4)):0;
    if(!mid){say('There is no reply to fork from yet.');return Promise.resolve(null)}
    return fork(mid);
  }

  window.ChatTools={
    fork:fork,forkLatest:forkLatest,exportChat:exportChat,
    exportMarkdown:function(){return exportChat('md')},
    exportJSON:function(){return exportChat('json')}
  };

  if(window.AirUI)window.AirUI.addMsgAction(function(m,isAi){
    if(!isAi||m.kind!=='text')return '';
    if(window.AirUI.shareAcl())return '';  // a shared chat cannot be copied into the host's chats
    return '<button type="button" class="msg-fork" title="Start a new chat that begins with this conversation up to here" onclick="event.stopPropagation();ChatTools.fork('+Number(m.id)+')">Fork</button>';
  });

  /* ---- header: Export button + tiny menu ---- */
  var btn,menu;
  function closeMenu(restore){
    if(!menu||menu.hidden)return;
    menu.hidden=true;btn.setAttribute('aria-expanded','false');
    if(restore)try{btn.focus({preventScroll:true})}catch(e){}
  }
  function openMenu(){
    var box=btn.closest('.chat-titlebar.more-open .chat-titlebar-actions');
    // Inside the phone's ... list the formats open in place under Export, so they never
    // sit on top of the Share row. On a wide screen the menu floats under the button.
    if(box){menu.classList.add('inline');box.insertBefore(menu,btn.nextSibling)}
    else{menu.classList.remove('inline');if(menu.parentNode!==document.body)document.body.appendChild(menu)}
    var r=btn.getBoundingClientRect();
    menu.hidden=false;btn.setAttribute('aria-expanded','true');
    if(!box){
      var w=menu.offsetWidth;
      menu.style.top=Math.round(r.bottom+6)+'px';
      menu.style.left=Math.max(8,Math.min(window.innerWidth-w-8,Math.round(r.right-w)))+'px';
    }
    var first=menu.querySelector('button');if(first)first.focus({preventScroll:true});
  }
  function mount(){
    var share=document.getElementById('chatShareBtn');
    if(!share)return false;
    if(document.getElementById('chatExportBtn'))return true;
    btn=document.createElement('button');
    btn.type='button';btn.id='chatExportBtn';btn.className='chat-share-btn ctools-export';
    btn.title='Save this chat as a file';btn.setAttribute('aria-label','Export this chat');
    btn.setAttribute('aria-haspopup','menu');btn.setAttribute('aria-expanded','false');
    btn.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19h14"/></svg>Export';
    share.parentNode.insertBefore(btn,share);
    menu=document.createElement('div');
    menu.className='ctools-menu';menu.hidden=true;menu.setAttribute('role','menu');
    menu.innerHTML='<button type="button" role="menuitem" data-fmt="md">Markdown</button><button type="button" role="menuitem" data-fmt="json">JSON</button>';
    document.body.appendChild(menu);
    btn.addEventListener('click',function(e){e.stopPropagation();menu.hidden?openMenu():closeMenu(true)});
    menu.addEventListener('click',function(e){
      var b=e.target.closest('button[data-fmt]');if(!b)return;
      closeMenu(true);exportChat(b.dataset.fmt);
    });
    document.addEventListener('click',function(e){if(!menu.hidden&&!menu.contains(e.target))closeMenu(false)});
    window.addEventListener('resize',function(){closeMenu(false)});
    document.addEventListener('keydown',function(e){
      if(e.key==='Escape'&&!menu.hidden){e.preventDefault();e.stopPropagation();closeMenu(true)}
    },true);
    return true;
  }
  if(!mount())document.addEventListener('DOMContentLoaded',mount);
})();
