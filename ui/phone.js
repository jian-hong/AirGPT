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
    var r=c.getBoundingClientRect(),v=76;
    /* Hub, RAG, OpenForge and Docs hide the message box (its top reads 0), which put the button on the
       Settings gear. With no box it rests low; with one it sits above it, never higher than the lower half. */
    if(r.height>0)v=Math.min(Math.max(60,Math.round(window.innerHeight-r.top+8)),Math.round(window.innerHeight/2));
    document.documentElement.style.setProperty('--phone-fab-b',v+'px');
  }

  /* 3. Chat title bar: Background tasks, Export and Share sit behind one small "more" button.
        It is a menu: Escape and a tap outside close it, and focus goes back to the button. */
  function more(){
    var bar=document.getElementById('chatTitleBar'),btn=document.getElementById('chatMoreBtn'),box=document.getElementById('chatTitleActions');
    if(!bar||!btn||!box)return;
    function all(){return [].slice.call(box.querySelectorAll('button'))}
    function shown(){return all().filter(function(b){return b.offsetParent})}
    function isOpen(){return bar.classList.contains('more-open')}
    function open(){
      bar.classList.add('more-open');btn.setAttribute('aria-expanded','true');box.setAttribute('role','menu');
      all().forEach(function(b){b.setAttribute('role','menuitem')});
      var f=shown()[0];if(f)f.focus({preventScroll:true});
    }
    function close(back){
      if(!isOpen())return;
      bar.classList.remove('more-open');btn.setAttribute('aria-expanded','false');box.removeAttribute('role');
      all().forEach(function(b){b.removeAttribute('role')});
      if(back)try{btn.focus({preventScroll:true})}catch(e){}
    }
    function inSub(t){return !!(t&&t.closest&&t.closest('.ctools-menu'))}
    btn.addEventListener('click',function(e){e.stopPropagation();isOpen()?close(true):open()});
    box.addEventListener('click',function(e){var b=e.target.closest('button');if(b&&b.id!=='chatExportBtn')close(false)});
    document.addEventListener('click',function(e){
      if(!isOpen())return;
      var b=inSub(e.target)&&e.target.closest('button[data-fmt]');
      if(b){close(true);return}
      if(!bar.contains(e.target)&&!inSub(e.target))close(false);
    });
    window.addEventListener('keydown',function(e){
      if(!isOpen()||e.defaultPrevented)return;
      if(e.key==='Escape'){e.preventDefault();close(true)}
      else if(e.key==='ArrowDown'||e.key==='ArrowUp'){
        var l=shown(),i=l.indexOf(document.activeElement);if(!l.length||!box.contains(document.activeElement))return;
        e.preventDefault();l[(i+(e.key==='ArrowDown'?1:l.length-1))%l.length].focus();
      }
    });
    bar.addEventListener('focusout',function(e){var t=e.relatedTarget;if(isOpen()&&t&&!bar.contains(t)&&!inSub(t))close(false)});
    new MutationObserver(function(){if(!bar.classList.contains('show'))close(false)}).observe(bar,{attributes:true,attributeFilter:['class']});
    var f=function(){if(!mq.matches)close(false)};
    if(mq.addEventListener)mq.addEventListener('change',f);else mq.addListener(f);
  }

  function start(){
    var ta=document.getElementById('input'),c=document.querySelector('.composer');
    if(!ta||!c)return;
    hint();fab();more();
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
