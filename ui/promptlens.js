/*
 * Prompt lens: shows what one reply was actually sent to the model.
 *
 * The numbers and text come from GET /api/chat/prompt-trace, which returns the record
 * the server wrote while it built the request. Nothing here rebuilds a prompt, so the
 * panel cannot show a block that was not sent. When there is no record it says so.
 *
 * window.PromptLens = { open(messageId), openLatest(), close(), refreshMeter() }
 */
(function(){
  'use strict';

  // Fixed slot per block. Order here is also the order of the bar and the rows.
  var ORDER=['system','instructions','question','history','memory','evidence','skill','tools'];
  var HELP={
    system:'Standing rules the model gets before anything else.',
    instructions:'How to answer: tone, honesty rules, diagram style.',
    question:'What you typed this turn.',
    history:'Earlier messages from this chat.',
    memory:'Notes pulled from your vault for this question.',
    evidence:'Pages and search results fetched for this turn.',
    skill:'Extra guidance for the current project lane.',
    tools:'Functions the model is allowed to call.'
  };

  var root,scrim,sheet,bodyEl,titleChips,copyBtn,saveBtn,lastFocus=null,current=null;

  function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
  function num(n){return Number(n||0).toLocaleString('en-US')}
  function short(n){n=Number(n||0);return n>=10000?Math.round(n/1000)+'k':n>=1000?(n/1000).toFixed(1)+'k':String(n)}
  function color(key){return 'var(--pl-'+(ORDER.indexOf(key)>=0?key:'tools')+')'}
  function sorted(secs){
    return (secs||[]).slice().sort(function(a,b){
      var ia=ORDER.indexOf(a.key),ib=ORDER.indexOf(b.key);
      return (ia<0?99:ia)-(ib<0?99:ib);
    });
  }
  function pct(part,total){
    if(!total)return '0%';
    var p=part/total*100;
    return (p>0&&p<1)?'<1%':Math.round(p)+'%';
  }

  function build(){
    if(root)return;
    root=document.createElement('div');
    root.className='plens-root';
    root.innerHTML=
      '<div class="plens-scrim" data-plens-close></div>'+
      '<section class="plens-sheet" role="dialog" aria-modal="true" aria-labelledby="plensTitle" tabindex="-1">'+
        '<div class="plens-grab" aria-hidden="true"></div>'+
        '<header class="plens-head"><div><h2 id="plensTitle">What the model saw</h2><div class="plens-sub" id="plensChips"></div></div>'+
        '<button type="button" class="plens-close" data-plens-close aria-label="Close">✕</button></header>'+
        '<div class="plens-body" id="plensBody"></div>'+
        '<footer class="plens-foot">'+
          '<button type="button" class="plens-btn primary" id="plensCopy">Copy prompt</button>'+
          '<button type="button" class="plens-btn" id="plensSave">Download JSON</button>'+
        '</footer>'+
      '</section>';
    document.body.appendChild(root);
    scrim=root.querySelector('.plens-scrim');
    sheet=root.querySelector('.plens-sheet');
    bodyEl=root.querySelector('#plensBody');
    titleChips=root.querySelector('#plensChips');
    copyBtn=root.querySelector('#plensCopy');
    saveBtn=root.querySelector('#plensSave');
    root.addEventListener('click',function(e){
      if(e.target.closest('[data-plens-close]'))close();
    });
    copyBtn.addEventListener('click',copyPrompt);
    saveBtn.addEventListener('click',saveJson);
    // Capture phase: the app has its own Escape handlers that should not also fire.
    document.addEventListener('keydown',function(e){
      if(e.key==='Escape'&&sheet.classList.contains('open')){e.preventDefault();e.stopPropagation();close()}
    },true);
  }

  function show(){
    build();
    lastFocus=document.activeElement;
    scrim.classList.add('open');
    sheet.classList.add('open');
    sheet.focus({preventScroll:true});
  }
  function close(){
    if(!sheet)return;
    scrim.classList.remove('open');
    sheet.classList.remove('open');
    if(lastFocus&&lastFocus.focus){try{lastFocus.focus({preventScroll:true})}catch(e){}}
  }

  function setActions(on){copyBtn.disabled=!on;saveBtn.disabled=!on}

  function renderEmpty(title,detail){
    current=null;
    titleChips.innerHTML='';
    bodyEl.innerHTML='<div class="plens-empty"><strong>'+esc(title)+'</strong><p>'+esc(detail)+'</p></div>';
    setActions(false);
  }

  function chips(rec){
    var t=rec.trace||{},out=[];
    out.push(t.route==='cortex'?'Via Cortex agent':'Direct to model');
    if(t.model)out.push(t.model);
    if(t.tier)out.push('Effort: '+t.tier);
    if(t.pipeline==='dual')out.push('Draft + verify');
    if(rec.created_at){
      try{out.push(new Date(rec.created_at*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}))}catch(e){}
    }
    titleChips.innerHTML=out.map(function(c){return '<span class="plens-chip">'+esc(c)+'</span>'}).join('');
  }

  function render(rec){
    current=rec;
    var t=rec.trace||{},secs=sorted(t.sections),total=Number(t.tokens_est||0);
    chips(rec);
    var html='';

    html+='<div class="plens-hero"><b>~'+num(total)+'</b><span>tokens sent</span></div>';
    var fine='Estimate from '+num(t.total_chars)+' characters (4 per token). No tokenizer runs here.';
    if(t.max_output_tokens)fine+=' Reply limit: '+num(t.max_output_tokens)+' tokens.';
    html+='<p class="plens-fine">'+esc(fine)+'</p>';

    if(t.opaque){
      html+='<div class="plens-callout"><b>Partial view.</b> This turn went through Cortex. You are seeing what AirGPT handed over. Cortex adds its own system prompt and tools, which AirGPT cannot see.</div>';
    }

    // The bar: one segment per block, sized by estimated tokens.
    html+='<div class="plens-bar" id="plensBar" role="group" aria-label="Prompt parts by size">';
    secs.forEach(function(s,i){
      var share=total?(s.tokens_est/total*100):0;
      html+='<button type="button" class="plens-seg" data-i="'+i+'" style="flex-grow:'+Math.max(share,0.0001).toFixed(4)+';flex-basis:0;background:'+color(s.key)+'"'+
            ' aria-label="'+esc(s.label)+', about '+num(s.tokens_est)+' tokens, '+pct(s.tokens_est,total)+'"></button>';
    });
    html+='<div class="plens-tip" id="plensTip" aria-hidden="true"></div></div>';

    html+='<ul class="plens-rows">';
    secs.forEach(function(s,i){
      var sub=s.note||HELP[s.key]||'';
      html+='<li><details class="plens-row" data-i="'+i+'"><summary>'+
        '<span class="plens-dot" style="background:'+color(s.key)+'"></span>'+
        '<span class="plens-name"><strong>'+esc(s.label)+(s.private?' <span aria-hidden="true">🔒</span>':'')+'</strong>'+(sub?'<small>'+esc(sub)+'</small>':'')+'</span>'+
        '<span class="plens-num">~'+num(s.tokens_est)+'</span>'+
        '<span class="plens-pct">'+pct(s.tokens_est,total)+'</span>'+
        '<span class="plens-caret" aria-hidden="true">▶</span></summary>';
      if(s.redacted){
        html+='<div class="plens-locked">Hidden on this device. These notes come from the host computer\'s vault, so the text only shows when you open AirGPT on that computer. The size above is real.</div>';
      }else{
        html+='<pre class="plens-text">'+esc(s.text||'')+(s.text_truncated?'\n\n[Shown cut here. The full block was '+num(s.chars)+' characters.]':'')+'</pre>';
      }
      html+='</details></li>';
    });
    html+='</ul>';

    var h=t.history;
    if(h&&h.budget_chars){
      var hist=secs.filter(function(s){return s.key==='history'})[0];
      var used=hist?hist.chars:0;
      html+='<div class="plens-block"><h3>Chat history budget</h3>'+
        '<div class="plens-budget" role="img" aria-label="'+num(used)+' of '+num(h.budget_chars)+' characters used"><i style="width:'+Math.min(100,used/h.budget_chars*100).toFixed(1)+'%"></i></div>'+
        '<p class="plens-fine">'+num(used)+' of '+num(h.budget_chars)+' characters. '+
        (h.dropped?num(h.dropped)+' older '+(h.dropped===1?'message was':'messages were')+' left out this turn.':'Nothing was left out this turn.')+'</p></div>';
    }

    if((t.notes||[]).length){
      html+='<div class="plens-block"><h3>Good to know</h3><ul class="plens-notes">'+
        t.notes.map(function(n){return '<li>'+esc(n)+'</li>'}).join('')+'</ul></div>';
    }
    bodyEl.innerHTML=html;
    bodyEl.scrollTop=0;
    setActions(true);
    wireBar(secs,total);
  }

  function wireBar(secs,total){
    var bar=bodyEl.querySelector('#plensBar'),tip=bodyEl.querySelector('#plensTip');
    if(!bar)return;
    function rowFor(i){return bodyEl.querySelector('.plens-row[data-i="'+i+'"]')}
    function on(seg){
      var i=+seg.dataset.i,s=secs[i];
      bar.classList.add('dim');seg.classList.add('on');
      var r=rowFor(i);if(r)r.classList.add('hl');
      tip.textContent=s.label+' · ~'+num(s.tokens_est)+' tokens · '+pct(s.tokens_est,total);
      var b=bar.getBoundingClientRect(),g=seg.getBoundingClientRect();
      tip.classList.add('show');
      var half=tip.offsetWidth/2,x=g.left-b.left+g.width/2;
      tip.style.left=Math.max(half,Math.min(b.width-half,x))+'px';
    }
    function off(seg){
      bar.classList.remove('dim');seg.classList.remove('on');tip.classList.remove('show');
      var r=rowFor(+seg.dataset.i);if(r)r.classList.remove('hl');
    }
    bar.querySelectorAll('.plens-seg').forEach(function(seg){
      seg.addEventListener('pointerenter',function(){on(seg)});
      seg.addEventListener('pointerleave',function(){off(seg)});
      seg.addEventListener('focus',function(){on(seg)});
      seg.addEventListener('blur',function(){off(seg)});
      seg.addEventListener('click',function(){
        var r=rowFor(+seg.dataset.i);
        if(!r)return;
        r.open=true;
        r.scrollIntoView({block:'nearest',behavior:'smooth'});
      });
    });
  }

  function promptText(){
    if(!current)return '';
    return sorted(current.trace.sections).map(function(s){
      var head='===== '+s.label+' (~'+s.tokens_est+' tokens) =====';
      return head+'\n'+(s.redacted?'[hidden on this device]':(s.text||''));
    }).join('\n\n');
  }
  function say(m){if(typeof window.toast==='function')window.toast(m)}
  function copyPrompt(){
    var text=promptText();
    if(!text)return;
    var done=function(){say('Prompt copied')},fail=function(){say('Copy failed. Use Download JSON instead.')};
    if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(text).then(done,fail);return}
    // Phones reach the host over plain http on the LAN, where the async clipboard
    // API does not exist. execCommand still works there.
    var ta=document.createElement('textarea');
    ta.value=text;ta.setAttribute('readonly','');ta.style.cssText='position:fixed;left:-9999px;top:0';
    document.body.appendChild(ta);ta.select();
    var ok=false;try{ok=document.execCommand('copy')}catch(e){}
    ta.remove();
    ok?done():fail();
  }
  function saveJson(){
    if(!current)return;
    var blob=new Blob([JSON.stringify(current,null,2)],{type:'application/json'});
    var a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download='airgpt-prompt-'+current.message_id+'.json';
    document.body.appendChild(a);a.click();a.remove();
    setTimeout(function(){URL.revokeObjectURL(a.href)},2000);
  }

  async function fetchTrace(query){
    var r=await window.api('/api/chat/prompt-trace?'+query);
    var j=null;
    try{j=await r.json()}catch(e){}
    return {status:r.status,body:j};
  }

  async function openWith(query){
    show();
    titleChips.innerHTML='';
    bodyEl.innerHTML='<div class="plens-empty"><p>Loading…</p></div>';
    setActions(false);
    var res;
    try{res=await fetchTrace(query)}
    catch(e){return renderEmpty('Could not reach AirGPT','The host did not answer. Check the connection and try again.')}
    if(res.status===200&&res.body&&res.body.trace)return render(res.body);
    if(res.status===404)return renderEmpty('No prompt record for this reply',
      'Replies made before this feature, and image or agent replies, were not recorded. New chat replies will show here.');
    if(res.status===401||res.status===403)return renderEmpty('Not available on this device',
      (res.body&&res.body.error)||'This device is not allowed to read prompt records.');
    renderEmpty('Something went wrong','The host answered with status '+res.status+'.');
  }

  // --- composer meter: size of the last prompt in this chat ----------------------
  var meter=null,meterKey='';
  function ensureMeter(){
    if(meter)return meter;
    var anchor=document.getElementById('modelDd');
    if(!anchor||!anchor.parentNode)return null;
    meter=document.createElement('button');
    meter.type='button';
    meter.className='plens-meter plens-root';
    meter.hidden=true;
    meter.addEventListener('click',function(){openLatest()});
    anchor.parentNode.insertBefore(meter,anchor);
    return meter;
  }
  function sessionId(){try{return Number(currentSession)||0}catch(e){return 0}}
  function lastReplyId(){
    var nodes=document.querySelectorAll('#chat .msg.ai-msg[id^="msg-"]');
    return nodes.length?nodes[nodes.length-1].id:'';
  }
  async function refreshMeter(force){
    var m=ensureMeter();
    if(!m)return;
    var sid=sessionId(),key=sid+':'+lastReplyId();
    if(!force&&key===meterKey)return;
    meterKey=key;
    if(!sid){m.hidden=true;return}
    var res;
    try{res=await fetchTrace('session_id='+sid)}catch(e){m.hidden=true;return}
    if(key!==meterKey)return;               // a newer refresh superseded this one
    if(res.status!==200||!res.body||!res.body.trace){m.hidden=true;return}
    var t=res.body.trace,total=Number(t.tokens_est||0);
    m.innerHTML='<span class="plens-meter-bar" aria-hidden="true">'+sorted(t.sections).map(function(s){
      return '<i style="flex:'+Math.max(s.tokens_est,1)+' 0 0;background:'+color(s.key)+'"></i>';
    }).join('')+'</span>~'+short(total);
    m.title='Last prompt in this chat: about '+num(total)+' tokens. Click to see what the model saw.';
    m.setAttribute('aria-label',m.title);
    m.hidden=false;
  }

  function open(messageId){return openWith('message_id='+encodeURIComponent(messageId))}
  function openLatest(){return openWith('session_id='+sessionId())}

  function start(){
    var chat=document.getElementById('chat');
    if(!chat)return;
    var timer=0;
    // The transcript re-renders on every poll and every streamed token. Only the
    // last reply id or the chat changing is worth a request.
    new MutationObserver(function(){
      clearTimeout(timer);
      timer=setTimeout(function(){refreshMeter(false)},500);
    }).observe(chat,{childList:true});
    setTimeout(function(){refreshMeter(true)},1500);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);
  else start();

  window.PromptLens={open:open,openLatest:openLatest,close:close,refreshMeter:function(){return refreshMeter(true)}};
})();
