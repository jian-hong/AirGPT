/*
 * Last turn: Edit your last question, Regenerate the last reply, and the "Stopped" mark.
 *
 * The buttons are written into every question and reply by AirUI.addMsgAction, then
 * shown only on the last turn of the open chat (CSS reads the classes set below). The
 * work is done by editLastUser() and regenerateLast() in the page; the server swaps
 * the turn (POST /api/chat/stream with replace_msg_id or regenerate_msg_id).
 *
 * Only the last turn can change. Keeping both versions (branching) is not built.
 */
(function(){
  'use strict';
  if(!window.AirUI)return;

  window.AirUI.addMsgAction(function(m,isAi){
    if(m.kind!=='text')return '';
    if(isAi){
      var out=m.ai_status==='stopped'?'<span class="msg-stopped" title="You stopped this reply before it finished">Stopped</span>':'';
      if(window.AirUI.shareAcl()==='view')return out;
      return out+'<button type="button" class="msg-regen" aria-label="Regenerate" title="Ask the same question again and replace this reply" onclick="event.stopPropagation();regenerateLast()">Regenerate</button>';
    }
    if(m.source!=='ai-chat'||window.AirUI.shareAcl()==='view')return '';
    return '<button type="button" class="msg-edit" aria-label="Edit" title="Put this message back in the box to change it" onclick="event.stopPropagation();editLastUser()">Edit</button>'
      +'<button type="button" class="msg-retry" aria-label="Try again" title="Ask this question again" onclick="event.stopPropagation();regenerateLast()">Try again</button>';
  });

  /* Mark the last turn after every draw of the chat. Nothing is marked while a reply is streaming. */
  var queued=false;
  function mark(){
    queued=false;
    var chat=document.getElementById('chat');if(!chat)return;
    var old=chat.querySelectorAll('.turn-last-user,.turn-last-ai,.turn-no-reply');
    for(var i=0;i<old.length;i++)old[i].classList.remove('turn-last-user','turn-last-ai','turn-no-reply');
    try{if(typeof syncEditChip==='function')syncEditChip()}catch(e){}
    if(chat.querySelector('#ai-stream,#pending-user,#sendFailCard,#gen-note'))return;  // a reply is still coming (maybe from another tab)
    var rows=chat.querySelectorAll('.msg[id^="msg-"]');
    if(!rows.length)return;
    var last=rows[rows.length-1];
    if(last.dataset.ai==='1'){
      last.classList.add('turn-last-ai');
      var prev=rows.length>1?rows[rows.length-2]:null;
      if(prev&&prev.dataset.ai!=='1')prev.classList.add('turn-last-user');
    }else{
      last.classList.add('turn-last-user','turn-no-reply');
    }
  }
  function later(){if(queued)return;queued=true;requestAnimationFrame(mark)}

  function start(){
    var chat=document.getElementById('chat');
    if(!chat){document.addEventListener('DOMContentLoaded',start,{once:true});return}
    new MutationObserver(later).observe(chat,{childList:true});
    later();
  }
  start();
})();
