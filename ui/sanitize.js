/*
 * Allow-list HTML cleaner, used for chat messages when DOMPurify is not available.
 * The browser parses the text into an inert document, then only a small set of
 * elements and attributes is kept. Everything else is removed.
 * window.AirSanitize = { clean(html) }   (tested in tests/sanitize.test.mjs)
 */
(function(root){
  'use strict';
  var HTML_NS='http://www.w3.org/1999/xhtml';
  var KEEP=('p br hr b strong i em u s del ins sub sup code pre kbd mark blockquote ul ol li dl dt dd '+
    'table thead tbody tfoot tr th td caption colgroup col h1 h2 h3 h4 h5 h6 a img span div details summary').split(' ');
  // Removed together with everything inside them.
  var DROP=('script style iframe frame frameset object embed applet form input button textarea select option '+
    'link meta base template noscript title head svg math audio video source track canvas').split(' ');
  var ATTRS={'*':['title'],code:['class'],a:['href','target','rel'],img:['src','alt'],
    td:['colspan','rowspan','align'],th:['colspan','rowspan','align'],ol:['start'],col:['span'],colgroup:['span'],
    details:['open']};
  var SCHEME=/^[a-z][a-z0-9+.\-]*:/i;

  // Plain relative links, http, https and mailto only. Control characters are
  // dropped first because browsers ignore them inside a scheme ("java\tscript:").
  function okUrl(v,image){
    var u=String(v).replace(/[\u0000- \u007f-\u009f]/g,'');
    if(image&&/^data:image\/(png|jpe?g|gif|webp);base64,[a-z0-9+\/=]*$/i.test(u))return true;
    if(/^(https?:|mailto:)/i.test(u))return !image||!/^mailto:/i.test(u);
    return !SCHEME.test(u);
  }

  function walk(parent){
    Array.prototype.slice.call(parent.childNodes).forEach(function(n){
      if(n.nodeType===3)return;
      if(n.nodeType!==1){parent.removeChild(n);return}
      var tag=n.localName;
      if(n.namespaceURI!==HTML_NS||DROP.indexOf(tag)>=0){parent.removeChild(n);return}
      if(KEEP.indexOf(tag)<0){
        // Unknown but harmless tag: keep its text, lose the tag.
        walk(n);
        while(n.firstChild)parent.insertBefore(n.firstChild,n);
        parent.removeChild(n);
        return;
      }
      var ok=(ATTRS[tag]||[]).concat(ATTRS['*']);
      Array.prototype.slice.call(n.attributes).forEach(function(a){
        var name=a.name.toLowerCase();
        if(ok.indexOf(name)<0||((name==='href'||name==='src')&&!okUrl(a.value,tag==='img')))n.removeAttribute(a.name);
      });
      if(tag==='code'&&n.hasAttribute('class')){
        var k=n.getAttribute('class').split(/\s+/).filter(function(c){return /^language-[\w+#.\-]{1,30}$/.test(c)});
        if(k.length)n.setAttribute('class',k.join(' '));else n.removeAttribute('class');
      }
      if(tag==='a'&&n.getAttribute('target')){n.setAttribute('rel','noopener noreferrer')}
      walk(n);
    });
  }

  function clean(html){
    var doc=new DOMParser().parseFromString('<body>'+String(html==null?'':html),'text/html');
    walk(doc.body);
    return doc.body.innerHTML;
  }

  root.AirSanitize={clean:clean};
  if(typeof module!=='undefined'&&module.exports)module.exports=root.AirSanitize;
})(typeof window!=='undefined'?window:this);
