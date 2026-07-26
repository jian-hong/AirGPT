from pathlib import Path
import re

p = Path(r"D:\AirGPT\index.html")
t = p.read_text(encoding="utf-8")

old = "function ragSetTab(t){ragState.tab=t;ragRenderSpace();}"
new = """function ragSetTab(t){
  if(ragState.tab==='build'&&t!=='build') ragMaybePromptPendingBuild();
  ragState.tab=t;ragRenderSpace();
}"""
print("ragSetTab", "ok" if old in t else "missing")
if old in t:
    t = t.replace(old, new, 1)

old2 = "toast('Build complete — ready for retrieval');"
idx = t.find(old2)
if idx >= 0 and "pendingBuild=false" not in t[idx : idx + 160]:
    t = t.replace(old2, old2 + "\n      ragState.pendingBuild=false;", 1)
    print("pending clear ok")
else:
    print("pending clear skip")

marker = "ragState.streaming=true;const sendBtn=$('ragAskSend')||$('ragSendBtn');if(sendBtn)sendBtn.disabled=true;"
if marker in t and "sleuthWords" not in t:
    insert_after = """  ragState.streaming=true;const sendBtn=$('ragAskSend')||$('ragSendBtn');if(sendBtn)sendBtn.disabled=true;
  const aiId='ragai-'+Date.now();
  if(msgs)msgs.insertAdjacentHTML('beforeend',`<div id="${aiId}" style="align-self:flex-start;max-width:min(860px,92%);padding:9px 13px;border-radius:14px;background:var(--surface2);line-height:1.5"><div class="ragthink rag-think"><span class="dot"></span><span class="t">Reading sources…</span></div><div class="rag-files-surfed" style="display:none;font-size:12px;opacity:.8;margin:4px 0 6px"></div><div class="ragbody"></div><div class="ragcite"></div></div>`);
  ragScrollMsgs();
  let acc='';let cites=[];let nVisited=0;let thoughts=[];let doneMeta={};
  const q1=s=>document.querySelector('#'+aiId+' '+s);
  const hideThink=()=>{const t=q1('.ragthink');if(t)t.style.display='none';};
"""
    replacement = """  ragState.streaming=true;const sendBtn=$('ragAskSend')||$('ragSendBtn');if(sendBtn)sendBtn.disabled=true;
  const aiId='ragai-'+Date.now();
  if(msgs)msgs.insertAdjacentHTML('beforeend',`<div id="${aiId}" style="align-self:flex-start;max-width:min(860px,92%);padding:9px 13px;border-radius:14px;background:var(--surface2);line-height:1.5"><div class="ragthink rag-think"><span class="spin"></span><span class="t">Gathering…</span></div><div class="rag-files-surfed" style="display:none;font-size:12px;opacity:.8;margin:4px 0 6px"></div><div class="ragbody"></div><div class="ragcite"></div></div>`);
  ragScrollMsgs();
  let acc='';let cites=[];let nVisited=0;let thoughts=[];let doneMeta={};
  const q1=s=>document.querySelector('#'+aiId+' '+s);
  const hideThink=()=>{const t=q1('.ragthink');if(t)t.style.display='none';};
  const sleuthWords=['Gathering…','Sleuthing…','Reading sources…','Cross-checking…','Tracing citations…','Weighing evidence…'];
  let sleuthI=0, lastBeat=Date.now(), stallTimer=null, sleuthTimer=null;
  const setThink=(txt,lost)=>{
    const box=q1('.ragthink');const el=q1('.ragthink .t');
    if(el)el.textContent=txt;
    if(box)box.classList.toggle('lost',!!lost);
  };
  sleuthTimer=setInterval(()=>{
    if(acc)return;
    sleuthI=(sleuthI+1)%sleuthWords.length;
    setThink(sleuthWords[sleuthI],false);
  },2200);
  stallTimer=setInterval(()=>{
    if(acc)return;
    if(Date.now()-lastBeat>28000){
      setThink('Connection slow — still waiting / reconnecting…',true);
    }
  },4000);
  const clearThinkTimers=()=>{try{clearInterval(sleuthTimer)}catch(e){};try{clearInterval(stallTimer)}catch(e){};};
"""
    if insert_after in t:
        t = t.replace(insert_after, replacement, 1)
        print("rotator ok")
    else:
        print("rotator block missing exact match")
else:
    print("rotator skip", marker in t, "sleuth" in t)

old4 = "if(j.type==='thinking'){const txt=j.text||'Thinking…';thoughts.push(txt);const t=q1('.ragthink .t');if(t&&!acc)t.textContent=txt;}"
new4 = "if(j.type==='thinking'){const txt=j.text||'Thinking…';thoughts.push(txt);lastBeat=Date.now();if(!acc)setThink(txt,false);}"
print("thinking", "ok" if old4 in t else "missing")
if old4 in t:
    t = t.replace(old4, new4, 1)

# Clear timers before streaming=false
needle = "ragState.streaming=false;if(sendBtn)sendBtn.disabled=false;ragScrollMsgs();\n}"
# Only in ragSend - find last occurrence after ragSend
rs = t.find("async function ragSend()")
re_end = t.find("// ===== Global @ / slash", rs)
chunk = t[rs:re_end]
if "clearThinkTimers" not in chunk and "ragState.streaming=false;if(sendBtn)sendBtn.disabled=false;ragScrollMsgs();" in chunk:
    chunk2 = chunk.replace(
        "}catch(e){hideThink();const b=q1('.ragbody');if(b)b.textContent='Answer failed: '+(e.message||e);}\n  ragState.streaming=false;if(sendBtn)sendBtn.disabled=false;ragScrollMsgs();\n}",
        "}catch(e){clearThinkTimers();hideThink();const b=q1('.ragbody');if(b)b.textContent='Answer failed: '+(e.message||e)+' — check connection.';}\n  clearThinkTimers();\n  ragState.streaming=false;if(sendBtn)sendBtn.disabled=false;ragScrollMsgs();\n}",
        1,
    )
    if chunk2 != chunk:
        t = t[:rs] + chunk2 + t[re_end:]
        print("clear timers ok")
    else:
        print("clear timers pattern missing")
else:
    print("clear timers skip")

# Brand click: open chats + cortex
t2, n = re.subn(
    r'(<div class="brand brand-exit")([^>]*)(>)',
    r'\1\2 onclick="openAirgptHome()" title="AirGPT — vault + Cortex"\3',
    t,
    count=1,
)
if n:
    t = t2
    print("brand onclick ok")
else:
    # try without brand-exit
    t2, n = re.subn(
        r'(<div class="brand")([^>]*)(>)',
        r'<div class="brand brand-exit"\2 onclick="openAirgptHome()" title="AirGPT — vault + Cortex">',
        t,
        count=1,
    )
    if n:
        t = t2
        print("brand onclick alt ok")
    else:
        print("brand missing")

if "function openAirgptHome" not in t:
    inject = """
function openAirgptHome(){
  try{leaveOverlayWorkspace?.()}catch(e){}
  sideView='chats';
  updateSideNav?.();
  showCenterProjects?.({asChats:true,keepSession:true});
  // Cortex rail companion — open agent surface without leaving vault
  setTimeout(()=>{try{if(window.bgTasks&&window.bgTasks.open){/* keep */} }catch(e){}},0);
  toast('Vault + chats · Cortex is in Agents');
}
"""
    anchor = "function showHubPage"
    if anchor in t:
        t = t.replace(anchor, inject + "\n" + anchor, 1)
        print("openAirgptHome injected")
    else:
        print("inject anchor missing")

# Increase chunk samples
t = t.replace(
    "const d=await api('/api/rag/spaces/'+sid+'/samples?limit=6')",
    "const d=await api('/api/rag/spaces/'+sid+'/samples?limit=18')",
    1,
)

p.write_text(t, encoding="utf-8")
print("wrote", len(t))
