/*
 * AirUI: the one place add-on modules hook into the chat shell.
 *
 * index.html is a single 890 KB file. Every feature that edits it collides with
 * every other one. Modules under /ui/ register here instead, so adding a feature
 * means adding files, not editing the page.
 *
 * Loaded before the main script. Modules load after it and register at load time;
 * the first transcript render waits on a network fetch, so it sees them all.
 */
(function(){
  'use strict';
  var msgActions=[];
  window.AirUI={
    /* fn(m, isAi) returns the HTML for one button in a message's meta row, or ''.
       `m` is the message row from the server (id, kind, source, text, session_id). */
    addMsgAction:function(fn){if(typeof fn==='function')msgActions.push(fn)},
    msgActionsHtml:function(m,isAi){
      var out='';
      for(var i=0;i<msgActions.length;i++){
        try{out+=msgActions[i](m,isAi)||''}
        catch(e){console.warn('[AirUI] message action failed',e)}
      }
      return out;
    }
  };
})();
