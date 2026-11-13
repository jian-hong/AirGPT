/*
 * Code blocks in chat messages get a small bar with the language and a Copy button.
 *
 * Additive, like the other ui/ modules: it watches #chat and decorates any <pre><code>
 * inside a message body that it has not seen yet, so it also covers streamed replies
 * (their body is redrawn on every token). The copied text is code.textContent, never
 * the bar, and the language comes from marked's "language-xxx" class.
 */
(function(){
  'use strict';

  function lang(code){
    var m=/(?:^|\s)language-([\w+#.-]{1,24})/.exec(code.className||'');
    return m?m[1]:'';
  }

  function writeClipboard(text){
    if(navigator.clipboard&&window.isSecureContext){
      return navigator.clipboard.writeText(text).then(function(){return true},function(){return legacy(text)});
    }
    return Promise.resolve(legacy(text));
  }
  // Plain http on the LAN has no async clipboard; a hidden textarea still works there.
  function legacy(text){
    var ta=document.createElement('textarea');
    ta.value=text;ta.setAttribute('readonly','');
    ta.style.cssText='position:fixed;top:-1000px;opacity:0';
    document.body.appendChild(ta);ta.select();
    var ok=false;
    try{ok=document.execCommand('copy')}catch(e){ok=false}
    ta.remove();
    return ok;
  }

  function decorate(pre){
    if(pre.dataset.cb)return;
    var code=pre.querySelector(':scope > code');
    if(!code)return;
    pre.dataset.cb='1';
    var bar=document.createElement('div');
    bar.className='cb-bar';
    var name=document.createElement('span');
    name.className='cb-lang';
    name.textContent=lang(code)||'code';
    var btn=document.createElement('button');
    btn.type='button';btn.className='cb-copy';btn.textContent='Copy';
    btn.setAttribute('aria-label','Copy code'+(lang(code)?' ('+lang(code)+')':''));
    btn.addEventListener('click',function(e){
      e.stopPropagation();
      writeClipboard(code.textContent).then(function(ok){
        btn.textContent=ok?'Copied':'Copy failed';
        btn.classList.toggle('bad',!ok);
        clearTimeout(btn._t);
        btn._t=setTimeout(function(){btn.textContent='Copy';btn.classList.remove('bad')},1600);
      });
    });
    bar.appendChild(name);bar.appendChild(btn);
    pre.insertBefore(bar,code);
  }

  function scan(root){
    var list=(root||document).querySelectorAll('#chat .msg .body pre');
    for(var i=0;i<list.length;i++)decorate(list[i]);
  }

  var queued=false;
  function later(){
    if(queued)return;
    queued=true;
    requestAnimationFrame(function(){queued=false;scan()});
  }

  function start(){
    var chat=document.getElementById('chat');
    if(!chat)return;
    new MutationObserver(later).observe(chat,{childList:true,subtree:true});
    scan();
  }

  window.CodeBlocks={scan:scan,lang:lang};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);
  else start();
})();
