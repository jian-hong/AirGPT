/* voice.js: a microphone button for the message box.
   Uses the browser's own SpeechRecognition. Where the browser has none, no button is made.
   It fills the box and never sends. Audio is handled by the browser's speech service;
   nothing is sent to an AirGPT server. */
(function(){
  'use strict';
  var SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR)return;
  var rec=null,listening=false,base='',finalText='',btn=null,pill=null,ta=null;

  function say(msg){try{if(typeof toast==='function')toast(msg)}catch(e){}}
  function setBox(text){
    ta.value=text;
    ta.dispatchEvent(new Event('input',{bubbles:true}));
  }
  function ui(on){
    listening=on;
    if(!btn)return;
    btn.classList.toggle('listening',on);
    btn.setAttribute('aria-pressed',on?'true':'false');
    btn.setAttribute('aria-label',on?'Stop voice input':'Voice input');
    btn.title=on?'Listening. Tap to stop.':'Speak your message (uses your browser\'s speech service)';
    pill.hidden=!on;
  }
  function join(a,b){
    a=a.replace(/\s+$/,'');b=b.replace(/^\s+/,'');
    return a&&b?a+' '+b:a+b;
  }
  function stop(){
    if(rec){try{rec.stop()}catch(e){}}
    ui(false);
  }
  function start(){
    if(listening){stop();return}
    ta=document.getElementById('input');if(!ta)return;
    rec=new SR();
    rec.lang=navigator.language||'en-US';
    rec.interimResults=true;
    rec.continuous=false;
    base=ta.value||'';finalText='';
    rec.onresult=function(ev){
      var interim='';
      for(var i=ev.resultIndex;i<ev.results.length;i++){
        var r=ev.results[i];
        if(r.isFinal)finalText=join(finalText,r[0].transcript);else interim=join(interim,r[0].transcript);
      }
      setBox(join(join(base,finalText),interim));
    };
    rec.onerror=function(ev){
      var e=ev&&ev.error;
      if(e==='not-allowed'||e==='service-not-allowed')say('The microphone is blocked. Allow it in your browser settings to use voice input.');
      else if(e==='no-speech')say('I did not hear anything. Tap the microphone and try again.');
      else if(e==='audio-capture')say('No microphone was found.');
      else if(e==='network')say('Voice input could not reach your browser\'s speech service.');
      else if(e!=='aborted')say('Voice input stopped: '+e);
      ui(false);
    };
    rec.onend=function(){ui(false);try{ta.focus()}catch(e){}};
    try{rec.start();ui(true)}catch(e){say('Voice input could not start.');ui(false)}
  }
  function build(){
    var actions=document.querySelector('.composer-actions'),send=document.getElementById('sendBtn');
    if(!actions||btn)return;
    btn=document.createElement('button');
    btn.type='button';btn.id='micBtn';btn.className='mic-btn';
    btn.setAttribute('aria-label','Voice input');btn.setAttribute('aria-pressed','false');
    btn.title='Speak your message (uses your browser\'s speech service)';
    btn.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>';
    btn.addEventListener('click',start);
    actions.insertBefore(btn,send||null);
    pill=document.createElement('div');
    pill.id='voiceStatus';pill.className='voice-status';pill.hidden=true;
    pill.setAttribute('role','status');
    pill.innerHTML='<span class="voice-dot" aria-hidden="true"></span>Listening. Tap the microphone to stop.';
    var inner=document.querySelector('.composer-inner');
    if(inner)inner.insertBefore(pill,inner.firstChild);
    var s=document.getElementById('sendBtn');
    if(s)s.addEventListener('click',function(){if(listening)stop()});
    var t=document.getElementById('input');
    if(t)t.addEventListener('keydown',function(e){if(e.key==='Enter'&&listening&&!e.shiftKey)stop()});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',build);else build();
})();
