/* phone.js: two phone fixes that CSS cannot do. Both only act at 760px and below. */
(function(){
  'use strict';
  var mq=window.matchMedia('(max-width:760px)');

  /* 1. The message box was blank on phones: the page clears its hint under 560px.
        Give it a short hint, except in the knowledge-space view that clears it on purpose. */
  function hint(){
    var ta=document.getElementById('input');
    if(!ta||!mq.matches||ta.placeholder)return;
    if(document.body.classList.contains('rag-mode'))return;
    var view='';try{view=sideView}catch(e){}
    if(view==='rag')return;
    ta.placeholder='Message AirGPT';
  }

  /* 2. Keep the report button just above the message box, wherever the box is
        (it grows with text and lifts with the keyboard). */
  function fab(){
    var c=document.querySelector('.composer');
    if(!c||!mq.matches)return;
    var b=document.getElementById('bugReportBtn');
    if(b&&b.title.indexOf('drag')>-1)b.title='Report a problem';
    var top=c.getBoundingClientRect().top;
    document.documentElement.style.setProperty('--phone-fab-b',Math.max(60,Math.round(window.innerHeight-top+8))+'px');
  }

  function start(){
    var ta=document.getElementById('input'),c=document.querySelector('.composer');
    if(!ta||!c)return;
    hint();fab();
    new MutationObserver(hint).observe(ta,{attributes:true,attributeFilter:['placeholder']});
    if(window.ResizeObserver)new ResizeObserver(fab).observe(c);
    window.addEventListener('resize',function(){hint();fab()});
    if(window.visualViewport){visualViewport.addEventListener('resize',fab);visualViewport.addEventListener('scroll',fab)}
    c.addEventListener('transitionend',fab);
    ta.addEventListener('input',fab);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
  /* the page builds some controls late */
  setTimeout(function(){hint();fab()},1500);
})();
