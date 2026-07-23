/* OpenIDE — extracted from index.html · source of truth: OpenIDE/ui/openide.js */
/* --- OpenIDE app-launch morph: Netie mark → topbar --- */
const NETIE_MARK_SVG=`<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect x="2.75" y="2.75" width="18.5" height="18.5" rx="2.2" stroke="currentColor" stroke-width="1.9" fill="rgba(255,255,255,.07)"/>
  <rect x="8.25" y="8.25" width="7.5" height="7.5" rx="1.1" fill="currentColor"/></svg>`;
let _oideMorphT0=0;
let _oideMorphFailSafe=0;
function openideMorphDismissHard(){
  const ov=document.getElementById('openideMorph');
  if(!ov)return;
  try{clearInterval(ov._t)}catch(e){}
  if(_oideMorphFailSafe){clearTimeout(_oideMorphFailSafe);_oideMorphFailSafe=0}
  ov.classList.add('out');
  setTimeout(()=>{try{ov.remove()}catch(e){}},280);
}
function openideMorphPlay(){
  if(document.getElementById('openideMorph'))return;
  _oideMorphT0=performance.now();
  const ov=document.createElement('div');
  ov.id='openideMorph';
  ov.setAttribute('role','status');
  ov.title='Click or press Esc to skip';
  ov.innerHTML=`<div class="oide-boot">
    <div class="oide-tile">${NETIE_MARK_SVG}</div>
    <div class="oide-name">OpenIDE</div>
    <div class="oide-bar"><i id="oideBarFill"></i></div>
    <div class="oide-step" id="oideStep">Mounting workspace…</div>
    <button type="button" class="oide-skip" id="oideMorphSkip">Skip</button>
  </div>`;
  document.body.appendChild(ov);
  requestAnimationFrame(()=>ov.classList.add('in'));
  const steps=['Mounting workspace…','Loading editor…','Attaching Cortex agents…'];
  let i=0;
  ov._t=setInterval(()=>{
    i=Math.min(i+1,steps.length-1);
    const s=document.getElementById('oideStep');if(s)s.textContent=steps[i];
    const f=document.getElementById('oideBarFill');if(f)f.style.width=Math.min(92,(i+1)*33)+'%';
  },420);
  const skip=()=>openideMorphDone(true);
  ov.addEventListener('click',e=>{if(e.target&&(e.target.id==='oideMorphSkip'||e.target===ov))skip()});
  $('oideMorphSkip')?.addEventListener('click',e=>{e.stopPropagation();skip()});
  // Never leave the user trapped behind a full-screen overlay
  if(_oideMorphFailSafe)clearTimeout(_oideMorphFailSafe);
  _oideMorphFailSafe=setTimeout(()=>openideMorphDone(true),2800);
}
function openideMorphDone(force){
  const ov=document.getElementById('openideMorph');if(!ov)return;
  if(_oideMorphFailSafe){clearTimeout(_oideMorphFailSafe);_oideMorphFailSafe=0}
  // Cap morph so warm machines don't sit on a fake floor; then settle Netie into topbar
  const wait=force?0:Math.max(0,520-(performance.now()-_oideMorphT0));
  setTimeout(()=>{
    try{
      clearInterval(ov._t);
      const f=document.getElementById('oideBarFill');if(f)f.style.width='100%';
      const mark=document.querySelector('.brand-mark');
      const tile=ov.querySelector('.oide-tile');
      if(!force&&mark&&tile&&!window.matchMedia('(prefers-reduced-motion: reduce)').matches){
        const from=tile.getBoundingClientRect();
        const to=mark.getBoundingClientRect();
        if(from.width>0&&to.width>0){
          const clone=tile.cloneNode(true);
          clone.style.cssText=`position:fixed;left:${from.left}px;top:${from.top}px;width:${from.width}px;height:${from.height}px;z-index:520;margin:0;transition:transform 1.05s cubic-bezier(.22,1,.36,1),opacity .9s ease;pointer-events:none;border-radius:22px`;
          document.body.appendChild(clone);
          const dx=(to.left+to.width/2)-(from.left+from.width/2);
          const dy=(to.top+to.height/2)-(from.top+from.height/2);
          const sx=Math.max(.18,to.width/from.width);
          requestAnimationFrame(()=>{
            clone.style.transform=`translate(${dx}px,${dy}px) scale(${sx})`;
            clone.style.opacity='0';
          });
          setTimeout(()=>clone.remove(),1100);
          mark.classList.remove('oide-settle');
          void mark.offsetWidth;
          mark.classList.add('oide-settle');
          setTimeout(()=>mark.classList.remove('oide-settle'),1200);
        }
      }
    }catch(e){/* never block dismiss */}
    setTimeout(()=>{
      try{ov.classList.add('out')}catch(e){}
      setTimeout(()=>{try{ov.remove()}catch(e){}},320);
    },force?40:180);
  },wait);
}
function onBrandClick(e){
  if(e&&e.target&&e.target.closest&&e.target.closest('.brand-tier,#brandTier,.tier-free,.tier-premium,.tier-icon'))return;
  if(document.body.classList.contains('openide-mode')){exitOpenIDE();return}
  if(document.body.classList.contains('openforge-mode')){showWorkspace('home');return}
}
function exitOpenIDE(){
  if(!document.body.classList.contains('openide-mode')&&sideView!=='openide')return;
  openideMorphDismissHard();
  try{history.replaceState({airgpt:'home'},'','#')}catch(e){}
  setOpenIDEMode(false);
  showSideView('chats');
  toast('Back to AirGPT');
}
if(!window._oideMorphEscBound){
  window._oideMorphEscBound=1;
  document.addEventListener('keydown',e=>{
    if(e.key!=='Escape')return;
    if(document.getElementById('openideMorph')){
      e.preventDefault();
      openideMorphDone(true);
    }
  });
}
function setOpenIDEMode(on){
  document.body.classList.toggle('openide-mode',!!on);
  const app=document.querySelector('.app');
  const title=$('appTitle');
  const mark=document.querySelector('.brand-mark');
  const brand=$('brandHome');
  if(brand){
    brand.classList.toggle('brand-exit',!!on);
    brand.title=on?'Exit OpenIDE · back to AirGPT':'AirGPT home';
  }
  if(on){
    if(title){if(!title.dataset.airgptTitle)title.dataset.airgptTitle=title.textContent;title.textContent='OpenIDE'}
    if(mark&&!mark.dataset.airgptMark){
      mark.dataset.airgptMark=mark.innerHTML;
      mark.innerHTML=NETIE_MARK_SVG;
    }
    try{history.pushState({airgpt:'openide'},'','#openide')}catch(e){}
  }else{
    if(title&&title.dataset.airgptTitle){title.textContent=title.dataset.airgptTitle;delete title.dataset.airgptTitle}
    if(mark&&mark.dataset.airgptMark){mark.innerHTML=mark.dataset.airgptMark;delete mark.dataset.airgptMark}
  }
  if(on&&app){
    app.classList.add('no-connect');
    $('connectCol')?.classList.add('collapsed');
    $('connectCol')?.classList.remove('open-sheet');
    // Slice 2: auto-collapse app left sidebar while in OpenIDE; restore on exit
    if(app.dataset.oidePrevSide==null){
      app.dataset.oidePrevSide=app.classList.contains('side-collapsed')?'1':'0';
    }
    app.classList.add('side-collapsed');
  }else if(app){
    if(app.dataset.oidePrevSide!=null){
      if(app.dataset.oidePrevSide==='0')app.classList.remove('side-collapsed');
      else app.classList.add('side-collapsed');
      delete app.dataset.oidePrevSide;
    }
    applyConnectLayout();
  }
  syncCollapseChevrons();
}
async function showOpenIDEPage(){
  const reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const warm=sessionStorage.getItem('airgpt_oide_warm')==='1';
  const firstBoot=!document.body.classList.contains('openide-mode');
  if(firstBoot&&!reduce&&!warm)openideMorphPlay();
  // If a prior boot left the overlay stuck, always clear it
  else if(document.getElementById('openideMorph'))openideMorphDismissHard();
  leaveOverlayWorkspace();
  sideView='openide';updateSideNav();closeSide();
  setOpenIDEMode(true);
  setProjectMode(false);
  const crp=$('cortexRightPanel');if(crp)crp.style.display='none';
  const bootFetch=(path)=>(typeof api==='function'?api(path):fetch(path)).then(r=>r.json()).catch(()=>({}));
  const withTimeout=(p,ms)=>Promise.race([
    p,
    new Promise(res=>setTimeout(()=>res({__timeout:true}),ms)),
  ]);
  let ws={ok:false}, backendJ={}, cortexJ={}, ts={}, lr={};
  try{
    const packed=await withTimeout(Promise.all([
      bootFetch('/api/workspace'),
      bootFetch('/api/openide/backend'),
      bootFetch('/api/cortex/settings'),
      bootFetch('/api/terminal/session'),
      bootFetch('/api/openide/last-run'),
    ]), 2500);
    if(Array.isArray(packed)){
      [ws, backendJ, cortexJ, ts, lr]=packed;
    }
  }catch(e){
    console.warn('OpenIDE boot fetch failed',e);
  }
  try{
  let backend=backendJ.backend||'local';
  let thinkMode=cortexJ.thinking_mode||'deep';
  window._openideThinkMode=thinkMode;
  if(ts&&ts.session_id)terminalSessionId=ts.session_id;
  if(lr&&lr.ok&&lr.run_id)window._openideCursorRunId=lr.run_id;
  const _esc=typeof esc==='function'?esc:(s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'));
  const rootLabel=ws.ok?_esc(ws.root):'No workspace';
  const sessTitle=ws.ok?_esc((ws.root||'').split(/[/\\\\]/).filter(Boolean).pop()||'OpenIDE'):'OpenIDE';
  const savedView=localStorage.getItem('airgpt_openide_view')==='editor'?'editor':'agents';
  const chipClass=thinkMode==='assist'?'assist':(thinkMode==='idle'?'idle':'');
  const chipLabel=thinkMode==='assist'?'Cortex · Assist':(thinkMode==='idle'?'Cortex · Idle':'Cortex · Deep');
  const leftW=localStorage.getItem('airgpt_oide_left')||'';
  const rightW=localStorage.getItem('airgpt_oide_right')||'';
  const leftCol=localStorage.getItem('airgpt_oide_left_col')==='1';
  // Always start right rail collapsed — open only via IDE↗
  const rightCol=true;
  localStorage.setItem('airgpt_oide_right_col','1');
  const folderShort=ws.ok?_esc(ws.name||(ws.root||'').split(/[/\\\\]/).filter(Boolean).pop()||'Folder'):'Folder';
  const folderTitle=ws.ok?_esc(ws.root||''):'Open a folder to start';
  const shellCls=['openide-shell','chat-page-enter','openide-view-'+savedView];
  if(leftCol)shellCls.push('left-collapsed');
  if(rightCol)shellCls.push('right-collapsed');
  const styleBits=[];
  if(leftW)styleBits.push('--oide-left:'+leftW);
  if(rightW)styleBits.push('--oide-right:'+rightW);
  const chatEl=$('chat');
  if(!chatEl){
    console.error('OpenIDE: #chat missing');
    openideMorphDismissHard();
    toast('OpenIDE failed to mount — refresh');
    return;
  }
  chatEl.innerHTML=`<div class="${shellCls.join(' ')}" id="openideShell"${styleBits.length?` style="${styleBits.join(';')}"`:''}>
    <aside class="openide-left" id="openideLeft">
      <button type="button" class="openide-rail-toggle left" id="openideToggleLeft" onclick="toggleOpenIDERail('left')" title="Collapse left panel">‹</button>
      <div class="openide-runs" id="openideRuns">
        <div class="openide-runs-hdr">
          <span>Agents</span>
          <button type="button" class="oide-new-agent" id="oideNewCortexBtn" onclick="newOpenIDECortexRun()" title="New Agent">New</button>
        </div>
        <div class="openide-repos" id="openideRepos">
          <div class="openide-rail-sec">Repositories</div>
          <div id="openideRepoList"></div>
        </div>
        <div class="openide-runs-list" id="openideRunsList" hidden></div>
      </div>
      <div class="openide-filepane-ide" id="openideFilePane">
        <div class="openide-filetabs">
          <button type="button" class="on" id="openideTabFiles" onclick="openideTab('files')">Files</button>
          <button type="button" id="openideTabGit" onclick="openideTab('git')">Git</button>
          <span id="openideRoot" title="${rootLabel}">${rootLabel}</span>
        </div>
        <div class="openide-tree" id="openideTree"><div class="empty">Open a folder</div></div>
        <div id="openideGit" style="display:none"></div>
      </div>
    </aside>
    <div class="oide-resizer" data-for="left" id="openideSplitLeft"></div>
    <section class="openide-center" id="openideChatPanel">
      <button type="button" class="openide-rail-toggle right oide-chat-collapse" id="openideToggleChat" onclick="closeOpenIDERightRail()" title="Collapse chat">›</button>
      <header class="openide-session-hdr">
        <h2 id="openideSessionTitle" title="${folderTitle}">${sessTitle}</h2>
        <button type="button" class="openide-chip ${chipClass}" id="openideCortexChip" onclick="toggleOpenIDECortex()" title="Cycle Cortex thinking mode">${chipLabel}</button>
        <div class="openide-view-toggle" role="tablist" aria-label="OpenIDE view">
          <button type="button" id="openideViewAgents" class="${savedView==='agents'?'on':''}" onclick="setOpenIDEView('agents')">Agents</button>
          <button type="button" id="openideViewEditor" class="${savedView==='editor'?'on':''}" onclick="setOpenIDEView('editor')">IDE</button>
        </div>
        <div class="openide-hdr-actions">
          <button type="button" class="btn" onclick="exitOpenIDE()" title="Exit OpenIDE (Esc)">← Home</button>
          <button type="button" class="btn" onclick="openKeyVault({banner:'OpenVault Key Vault — OpenFree, BYOK, CLI, OpenShip, mesh'})" title="OpenVault Key Vault">Keys</button>
          <button type="button" class="btn" id="openideOvBtn" onclick="openideConnectOpenVault()" title="Connect D:\\OpenVault mesh">Vault</button>
        </div>
      </header>
      <div class="openide-transcript" id="openideTranscript">
        <div class="openide-empty-hint" id="openideEmptyHint">
          <h3>Create an app</h3>
          <div class="oide-empty-sub">One prompt → scaffold → Cortex finishes it. OpenFree keys in Key Vault.</div>
          <div class="openide-empty-ctas">
            <button type="button" class="primary" onclick="openideCreateApp()">Create app</button>
            <button type="button" onclick="openideShareLanApp()">Share LAN</button>
            <button type="button" onclick="openKeyVault({banner:'OpenVault Key Vault — enable OpenFree or paste a free key'})">Keys</button>
            <button type="button" onclick="openIDEWorkspace()">Browse</button>
            <button type="button" onclick="openideNewFolder()">New folder</button>
            <button type="button" onclick="openideGithubRepo()">GitHub</button>
            <button type="button" onclick="openideAutoRepos()">Auto repos</button>
          </div>
        </div>
        <div id="openideDiff"></div>
      </div>
      <div class="openide-statusbar">
        <span class="st-live" id="openideLiveDot">●</span>
        <span class="st-muted" id="openideStatus">${ws.ok?'Workspace ready':'Open a folder to start'}</span>
        <span class="openide-diffstat" id="openideDiffStat"></span>
        <button type="button" class="btn" id="openideContinueBtn" onclick="continueOpenIDEAgent()" style="display:none" title="Resume last run">Continue</button>
        <button type="button" class="openide-pr-btn" id="openideCreatePr" onclick="openideCreatePR()" title="Create PR when there are changes">Create PR</button>
      </div>
      <div class="openide-composer">
        <div class="openide-composer-inner">
          <div class="oide-agent-bar">
            <div class="oide-agent-bar-top">
              <div class="oide-glass-dd" id="oideFolderDd">
                <button type="button" class="oide-glass-btn" id="oideFolderBtn" title="${folderTitle}" onclick="toggleOideGlassMenu('oideFolderDd')">
                  <span class="oide-btn-label" id="oideFolderLabel">${folderShort}</span><span class="dd-caret">▾</span>
                </button>
                <div class="oide-glass-menu" id="oideFolderMenu"></div>
              </div>
              <div class="oide-glass-dd" id="oideBranchDd">
                <button type="button" class="oide-glass-btn" id="oideBranchBtn" title="Git branch" onclick="toggleOideGlassMenu('oideBranchDd')">
                  <span class="oide-btn-label" id="oideBranchLabel">branch</span><span class="dd-caret">▾</span>
                </button>
                <div class="oide-glass-menu" id="oideBranchMenu">
                  <input class="og-search" id="oideBranchSearch" placeholder="Search branches…" oninput="filterOideBranchMenu(this.value)" onclick="event.stopPropagation()"/>
                  <div id="oideBranchList"><div class="og-empty">No branches available</div></div>
                </div>
              </div>
              <textarea id="openidePrompt" class="oide-prompt-inline" placeholder="Describe an app… or Plan / Build · / skills · @ files" oninput="openideMentionPicker(this)" onkeydown="openidePromptKeydown(event)"></textarea>
            </div>
            <div class="oide-agent-bar-bot">
              <div class="oide-glass-dd" id="oideModesDd">
                <button type="button" class="oide-glass-btn oide-modes-btn" id="oideNewAgentBtn" title="New Agent" onclick="newOpenIDECortexRun();closeAllOideGlassMenus()">New</button>
                <button type="button" class="oide-glass-btn" id="oideModeChip" title="Modes" onclick="toggleOideGlassMenu('oideModesDd')" style="min-width:auto;padding:4px 8px"><span id="oideModeLabel">Ask</span><span class="dd-caret">▾</span></button>
                <div class="oide-glass-menu" id="oideModesMenu">
                  <button type="button" onclick="newOpenIDECortexRun();closeAllOideGlassMenus()"><span>New Agent</span><span class="og-hint">fresh run</span></button>
                  <button type="button" data-mode="plan" onclick="setOideMode('plan')"><span>Plan</span><span class="og-hint">outline first</span></button>
                  <button type="button" data-mode="debug" onclick="setOideMode('debug')"><span>Debug</span><span class="og-hint">find root cause</span></button>
                  <button type="button" data-mode="multitask" onclick="setOideMode('multitask')"><span>Multitask</span><span class="og-hint">queue parallel</span></button>
                  <button type="button" data-mode="ask" onclick="setOideMode('ask')"><span>Ask</span><span class="og-hint">read-only</span></button>
                  <button type="button" onclick="openideCreateApp();closeAllOideGlassMenus()"><span>Create app</span><span class="og-hint">one-prompt scaffold</span></button>
                </div>
              </div>
              <div class="oide-glass-dd oide-tier-dd" id="oideTierDd">
                <button type="button" class="oide-glass-btn" id="oideTierBtn" title="Model tier" onclick="toggleOideGlassMenu('oideTierDd')">
                  <span class="oide-btn-label" id="oideTierLabel">High</span><span class="dd-caret">▾</span>
                </button>
                <div class="oide-glass-menu" id="oideTierMenu">
                  <button type="button" data-tier="max" onclick="setOideModelTier('max')"><strong>Max</strong><span class="og-hint">full reasoner</span></button>
                  <button type="button" data-tier="high" onclick="setOideModelTier('high')"><strong>High</strong><span class="og-hint">thinking on</span></button>
                  <button type="button" data-tier="basic" onclick="setOideModelTier('basic')"><strong>Basic</strong><span class="og-hint">fast · no think</span></button>
                </div>
              </div>
              <button type="button" class="oide-think-btn on" id="oideThinkBtn" title="Toggle thinking" aria-pressed="true" onclick="toggleOideThink()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
              </button>
              <button type="button" class="btn primary" id="openideRunBtn" onclick="runOpenIDEAgent()">Run</button>
            </div>
          </div>
          <div id="openideMentionPick"></div>
        </div>
      </div>
    </section>
    <div class="oide-resizer" data-for="right" id="openideSplitRight"></div>
    <aside class="openide-workspace" id="openideWorkspace">
      <button type="button" class="openide-rail-toggle right" id="openideToggleRight" onclick="closeOpenIDERightRail()" title="Collapse panel">›</button>
      <div class="openide-rail-sec">Open Tabs</div>
      <div class="openide-open-tabs" id="openideOpenTabs">
        <div class="openide-open-tab on" data-tab="agent" onclick="openideSelectOpenTab(this)"><span>Agent</span></div>
      </div>
      <div class="openide-on-ws" id="openideOnWs">
        <strong id="openideOnWsLabel">On ${folderShort}</strong>
        <span class="ows-stat" id="openideOnWsStat"></span>
      </div>
      <div class="openide-work-tabs">
        <button type="button" id="openideWorkChanges" onclick="openideWorkTab('changes')">Changes</button>
        <button type="button" class="on" id="openideWorkBrowser" onclick="openideWorkTab('browser')">Browser</button>
        <button type="button" id="openideWorkTerminal" onclick="openideWorkTab('terminal')">Terminal</button>
        <button type="button" id="openideWorkEditor" onclick="openideWorkTab('editor')">Files</button>
        <span class="oide-work-spacer"></span>
      </div>
      <div class="openide-preview on" id="openidePreviewPane">
        <div class="openide-browser-chrome">
          <span class="tab">Preview</span>
          <input id="openidePreviewUrl" placeholder="http://127.0.0.1:3000" value="" onkeydown="if(event.key==='Enter')openideLoadPreview(this.value)"/>
          <button type="button" class="btn" onclick="openideLoadPreview($('openidePreviewUrl').value)">Go</button>
        </div>
        <div class="openide-app-chips" id="openideAppChips"></div>
        <iframe id="openidePreviewFrame" title="App preview" sandbox="allow-scripts allow-same-origin allow-forms allow-popups"></iframe>
      </div>
      <div class="openide-changes" id="openideChangesPane" style="padding:10px;overflow:auto">
        <div class="hint" id="openideChangesEmpty">No pending write previews</div>
        <div id="openideChangesStack"></div>
      </div>
      <div class="openide-term-pane" id="openideTermPane">
        <div class="openide-term-wrap" id="openideTermWrapSolo" style="height:auto;flex:1;max-height:none;border:0">
          <pre id="openideTermSolo"></pre>
          <div class="openide-term-row">
            <input id="openideCmdSolo" placeholder="pytest · npm test · git status…" onkeydown="if(event.key==='Enter')runOpenIDECmd(true)"/>
            <button type="button" class="btn" onclick="runOpenIDECmd(true)">Run</button>
          </div>
        </div>
      </div>
      <div class="openide-editor-pane" id="openideEditorPane">
        <div class="openide-editor" id="openideEditor"><pre id="openidePre">// Open a file from the tree</pre></div>
        <div class="openide-term-wrap" id="openideTermWrap">
          <div class="oide-term-resizer" id="openideTermSplit"></div>
          <pre id="openideTerm"></pre>
          <div class="openide-term-row">
            <input id="openideCmd" placeholder="pytest · npm test · git status…" onkeydown="if(event.key==='Enter')runOpenIDECmd()"/>
            <button type="button" class="btn" onclick="runOpenIDECmd()">Run</button>
          </div>
        </div>
      </div>
    </aside>
  </div>`;
  window._openidePendingWrite=null;
  window._openidePlus=0;window._openideMinus=0;
  window._openideGitBundleLoaded=false;
  window._openideRuns=loadOpenIDERuns();
  if(!window._openideCursorRunId)window._openideCursorRunId='';
  window._openideAgentMode=window._openideAgentMode||'ask';
  try{renderOpenIDEAppChips()}catch(e){console.warn(e)}
  try{renderOpenIDERepos()}catch(e){console.warn(e)}
  try{renderOpenIDERunsList()}catch(e){console.warn(e)}
  try{syncOpenIDEAgentTabs()}catch(e){console.warn(e)}
  try{bindOpenIDEResizers()}catch(e){console.warn(e)}
  try{syncOpenIDERailToggles()}catch(e){console.warn(e)}
  try{syncOideAgentBar()}catch(e){console.warn(e)}
  try{renderOideFolderMenu()}catch(e){console.warn(e)}
  refreshOpenIDEFingerprint().then(()=>{syncOideBranchLabel();loadOideBranches()}).catch(()=>{});
  if(ws.ok)rememberOideWorkspace(ws.root,ws.name);
  if(!ws.ok){
    $('oideNewCortexBtn')?.classList.add('on');
    openideShowEmptyHint(true);
  }else{
    $('oideNewCortexBtn')?.classList.remove('on');
    // Keep a slim create-app tip until first transcript message
    const hasMsgs=$('openideTranscript')?.querySelector('.openide-msg');
    openideShowEmptyHint(!hasMsgs);
  }
  if(window._openidePendingNewAgent){
    window._openidePendingNewAgent=false;
    setOpenIDEView('agents');
    openideShowEmptyHint(false);
    setTimeout(()=>$('openidePrompt')?.focus(),40);
  }
  if(window._openideCursorRunId){const b=$('openideContinueBtn');if(b)b.style.display=''}
  // Defer heavy git_summary (full diff) until Git/Changes — light fingerprint already covers status bar
  if(ws.ok){
    refreshOpenIDETree();
    api('/api/git/fingerprint?light=1').then(r=>r.json()).then(fp=>{
      if(!fp||!fp.ok)return;
      window._openideFingerprint=fp;
      const dirty=(fp.dirty_count||0)>0;
      const btn=$('openideCreatePr');
      if(btn){btn.disabled=!dirty;btn.classList.toggle('show',!!dirty)}
      updateOpenIDEOnWsStat();
    }).catch(()=>{});
  }
  const frame=$('openidePreviewFrame');if(frame)frame.removeAttribute('src');
  if(savedView==='editor')openideWorkTab('editor');
  else openideWorkTab('browser');
  }catch(err){
    console.error('OpenIDE mount error',err);
    toast('OpenIDE hit a snag — overlay cleared');
  }finally{
    if(firstBoot&&!reduce&&!warm)openideMorphDone();
    else openideMorphDismissHard();
    try{sessionStorage.setItem('airgpt_oide_warm','1')}catch(e){}
  }
}
function toggleOpenIDECortex(){
  const order=['assist','deep','idle'];
  const cur=(window._openideThinkMode||'deep').toLowerCase();
  const next=order[(order.indexOf(cur)+1)%order.length];
  window._openideThinkMode=next;
  const chip=$('openideCortexChip');
  if(chip){
    chip.className='openide-chip'+(next==='assist'?' assist':(next==='idle'?' idle':''));
    chip.textContent=next==='assist'?'Cortex · Assist':(next==='idle'?'Cortex · Idle':'Cortex · Deep');
  }
  api('/api/cortex/settings',{method:'POST',body:JSON.stringify({thinking_mode:next})}).catch(()=>{});
  toast('Thinking: '+next);
}
function openideShowHelp(){
  openideAppendTranscript(`<div class="openide-help"><strong>OpenIDE help</strong>
    <ol>
      <li><b>Folder</b> — bind a project (path-jailed).</li>
      <li><b>Keys</b> — paste BYO keys (Groq / OpenRouter / Cursor) or enable OmniRoute free gateway.</li>
      <li><b>Run</b> — agent proposes writes; nothing hits disk until Approve.</li>
      <li><b>Git</b> — Fetch latest, then Create PR (needs <code>gh</code>).</li>
      <li><b>Cortex chip</b> — cycle Assist / Deep / Idle for the next run.</li>
    </ol>
    <button type="button" class="btn primary" style="margin-top:8px" onclick="openKeyVault()">Open Key Vault</button>
  </div>`);
}
function setOpenIDEView(which){
  const view=which==='editor'?'editor':'agents';
  localStorage.setItem('airgpt_openide_view',view);
  const shell=$('openideShell')||document.querySelector('.openide-shell');
  if(shell){
    shell.classList.remove('openide-view-editor','openide-view-agents');
    shell.classList.add('openide-view-'+view);
  }
  $('openideViewAgents')?.classList.toggle('on',view==='agents');
  $('openideViewEditor')?.classList.toggle('on',view==='editor');
  syncOpenIDERailToggles();
  if(view==='editor')openideWorkTab('editor');
  else openideWorkTab('browser');
}
function openideWorkTab(which){
  const tab=which==='changes'?'changes':(which==='terminal'?'terminal':(which==='editor'?'editor':'browser'));
  const prev=$('openidePreviewPane'),ch=$('openideChangesPane'),ed=$('openideEditorPane'),term=$('openideTermPane');
  const bB=$('openideWorkBrowser'),bC=$('openideWorkChanges'),bE=$('openideWorkEditor'),bT=$('openideWorkTerminal');
  prev?.classList.toggle('on',tab==='browser');
  ch?.classList.toggle('on',tab==='changes');
  ed?.classList.toggle('on',tab==='editor');
  term?.classList.toggle('on',tab==='terminal');
  bB?.classList.toggle('on',tab==='browser');
  bC?.classList.toggle('on',tab==='changes');
  bE?.classList.toggle('on',tab==='editor');
  bT?.classList.toggle('on',tab==='terminal');
  if(tab==='browser'){
    const frame=$('openidePreviewFrame');
    const url=($('openidePreviewUrl')?.value||'').trim();
    if(frame&&!frame.getAttribute('src')&&url&&!/127\.0\.0\.1:8765|localhost:8765/i.test(url)){
      openideLoadPreview(url);
    }
  }
  if(tab==='changes'){
    if(!window._openideGitBundleLoaded)loadOpenIDEGitBundle().then(()=>{window._openideGitBundleLoaded=true});
  }
  if(tab==='terminal'){
    openOpenIDERightRail();
    $('openideCmdSolo')?.focus();
  }
}
function openideSelectOpenTab(el){
  document.querySelectorAll('#openideOpenTabs .openide-open-tab').forEach(x=>x.classList.remove('on'));
  el?.classList.add('on');
  const kind=el?.dataset?.tab||'agent';
  if(kind==='file'){setOpenIDEView('editor');openideWorkTab('editor')}
  else if(kind==='browser'){openOpenIDERightRail();openideWorkTab('browser')}
  else setOpenIDEView('agents');
}
/** @deprecated alias — kept for older call sites */
function openideRightTab(which){
  if(which==='files'){setOpenIDEView('editor');openideWorkTab('editor');return}
  if(which==='terminal'){openideWorkTab('terminal');return}
  openideWorkTab(which==='changes'?'changes':'browser');
}
function openideTab(which){
  const tree=$('openideTree'),git=$('openideGit');
  const tabF=$('openideTabFiles'),tabG=$('openideTabGit');
  if(!tree||!git)return;
  const files=which!=='git';
  tree.style.display=files?'':'none';
  git.style.display=files?'none':'';
  tabF?.classList.toggle('on',files);
  tabG?.classList.toggle('on',!files);
  if(!files)refreshOpenIDEGit();
}
function toggleOpenIDERail(side){
  const shell=$('openideShell');if(!shell)return;
  if(side==='right'){
    // Close-only — open exclusively via openOpenIDERightRail / IDE↗
    if(shell.classList.contains('right-collapsed'))return;
    closeOpenIDERightRail();
    return;
  }
  const key='left-collapsed';
  const on=!shell.classList.contains(key);
  shell.classList.toggle(key,on);
  localStorage.setItem('airgpt_oide_left_col',on?'1':'0');
  syncOpenIDERailToggles();
}
function openOpenIDERightRail(){
  if(!document.body.classList.contains('openide-mode')){
    showOpenIDEPage().then(()=>openOpenIDERightRail());
    return;
  }
  const shell=$('openideShell');if(!shell)return;
  shell.classList.remove('right-collapsed');
  localStorage.setItem('airgpt_oide_right_col','0');
  syncOpenIDERailToggles();
}
function closeOpenIDERightRail(){
  const shell=$('openideShell');if(!shell)return;
  if(shell.classList.contains('right-collapsed'))return;
  shell.classList.add('right-collapsed');
  localStorage.setItem('airgpt_oide_right_col','1');
  syncOpenIDERailToggles();
}
function syncOpenIDERailToggles(){
  const shell=$('openideShell');if(!shell)return;
  const leftOn=shell.classList.contains('left-collapsed');
  const rightOn=shell.classList.contains('right-collapsed');
  const tl=$('openideToggleLeft'),tr=$('openideToggleRight');
  if(tl){tl.textContent=leftOn?'›':'‹';tl.title=leftOn?'Expand left panel':'Collapse left panel'}
  if(tr){
    tr.textContent='›';
    tr.title='Collapse panel';
  }
  const ideBtn=$('openideIdeBtn');
  if(ideBtn)ideBtn.title=rightOn?'Open IDE panel':'IDE panel open — use › to collapse';
}
function oideWsRecents(){
  try{return JSON.parse(localStorage.getItem('airgpt_ws_recents')||'[]')}catch(e){return[]}
}
function rememberOideWorkspace(path,name){
  if(!path)return;
  const n=name||String(path).split(/[/\\]/).filter(Boolean).pop()||path;
  const list=oideWsRecents().filter(x=>x&&x.path&&x.path!==path);
  list.unshift({path,name:n,at:Date.now()});
  localStorage.setItem('airgpt_ws_recents',JSON.stringify(list.slice(0,12)));
}
function closeAllOideGlassMenus(){
  document.querySelectorAll('.oide-glass-dd.open').forEach(el=>el.classList.remove('open'));
}
if(!window._oideGlassClickBound){
  window._oideGlassClickBound=1;
  document.addEventListener('click',e=>{
    if(!e.target.closest?.('.oide-glass-dd'))closeAllOideGlassMenus();
  });
}
function toggleOideGlassMenu(id){
  const dd=$(id);if(!dd)return;
  const was=dd.classList.contains('open');
  closeAllOideGlassMenus();
  if(!was){
    dd.classList.add('open');
    if(id==='oideBranchDd')loadOideBranches();
    if(id==='oideFolderDd')renderOideFolderMenu();
  }
}
function syncOideAgentBar(){
  const lab=$('oideTierLabel');
  if(lab)lab.textContent=(typeof MODEL_TIER_LABELS!=='undefined'&&MODEL_TIER_LABELS[modelTier])||modelTier||'High';
  document.querySelectorAll('#oideTierMenu button[data-tier]').forEach(b=>{
    b.classList.toggle('on',b.dataset.tier===modelTier);
  });
  const think=$('oideThinkBtn');
  if(think){
    const allow=typeof thinkingAllowed==='function'?thinkingAllowed():modelTier!=='basic';
    think.classList.toggle('hidden-tier',!allow);
    think.classList.toggle('on',allow&&thinkingEnabled);
    think.setAttribute('aria-pressed',allow&&thinkingEnabled?'true':'false');
  }
  syncOideBranchLabel();
  const folderLab=$('oideFolderLabel');
  const root=$('openideRoot')?.textContent||'';
  if(folderLab&&root&&root!=='No workspace'){
    folderLab.textContent=root.split(/[/\\]/).filter(Boolean).pop()||folderLab.textContent;
  }
}
function setOideModelTier(tier){
  setModelTier(tier);
  syncOideAgentBar();
  closeAllOideGlassMenus();
}
function toggleOideThink(){
  if(typeof thinkingAllowed==='function'&&!thinkingAllowed()){toast('Thinking unavailable on Basic');return}
  thinkingEnabled=!thinkingEnabled;
  localStorage.setItem('airgpt_thinking',thinkingEnabled?'1':'0');
  syncOideAgentBar();
  if(typeof updateModelUi==='function')updateModelUi();
  toast(thinkingEnabled?'Thinking on':'Thinking off');
}
function setOideMode(mode){
  window._openideAgentMode=mode;
  closeAllOideGlassMenus();
  const lab=$('oideModeLabel');
  if(lab)lab.textContent=(mode||'ask').charAt(0).toUpperCase()+(mode||'ask').slice(1);
  document.querySelectorAll('#oideModesMenu [data-mode]').forEach(b=>{
    b.classList.toggle('on',b.getAttribute('data-mode')===mode);
  });
  if(mode==='debug'){
    window._openideThinkMode='deep';
    api('/api/cortex/settings',{method:'POST',body:JSON.stringify({thinking_mode:'deep'})}).catch(()=>{});
    const chip=$('openideCortexChip');
    if(chip){chip.className='openide-chip';chip.textContent='Cortex · Deep'}
    toast('Mode: Debug · Deep thinking');
  }else if(mode==='plan'){
    window._openideThinkMode='assist';
    api('/api/cortex/settings',{method:'POST',body:JSON.stringify({thinking_mode:'assist'})}).catch(()=>{});
    const chip=$('openideCortexChip');
    if(chip){chip.className='openide-chip assist';chip.textContent='Cortex · Assist'}
    toast('Mode: Plan · Assist');
  }else if(mode==='ask'){
    window._openideThinkMode='idle';
    api('/api/cortex/settings',{method:'POST',body:JSON.stringify({thinking_mode:'idle'})}).catch(()=>{});
    const chip=$('openideCortexChip');
    if(chip){chip.className='openide-chip idle';chip.textContent='Cortex · Idle'}
    toast('Mode: Ask · read-focused');
  }else{
    window._openideThinkMode='deep';
    api('/api/cortex/settings',{method:'POST',body:JSON.stringify({thinking_mode:'deep'})}).catch(()=>{});
    const chip=$('openideCortexChip');
    if(chip){chip.className='openide-chip';chip.textContent='Cortex · Deep'}
    toast('Mode: Multitask · queued');
  }
}
function renderOideFolderMenu(){
  const host=$('oideFolderMenu');if(!host)return;
  const rec=oideWsRecents();
  const cur=($('openideRoot')?.getAttribute('title')||$('openideRoot')?.textContent||'').trim();
  let html='<div class="og-sec">Recents</div>';
  if(!rec.length)html+='<div class="og-empty">No recent folders</div>';
  else{
    html+=rec.map(r=>{
      const on=cur&&(cur===r.path||cur.endsWith(r.name))?' on':'';
      return `<button type="button" class="${on.trim()}" onclick="openIDEWorkspace(${JSON.stringify(r.path)})"><span>${esc(r.name||r.path)}</span></button>`;
    }).join('');
  }
  html+=`<div class="og-sec">Open</div>
    <button type="button" onclick="openideCreateApp()"><span>Create app</span><span class="og-hint">One prompt</span></button>
    <button type="button" onclick="openIDEWorkspace()"><span>Browse…</span><span class="og-hint">This PC</span></button>
    <button type="button" onclick="openideNewFolder()"><span>New folder</span><span class="og-hint">Create</span></button>
    <button type="button" onclick="openideGithubRepo()"><span>GitHub repo</span><span class="og-hint">Clone</span></button>
    <button type="button" onclick="openideAutoRepos()"><span>Auto repos</span><span class="og-hint">Recents</span></button>`;
  host.innerHTML=html;
}
function syncOideBranchLabel(){
  const lab=$('oideBranchLabel');
  const fp=window._openideFingerprint||{};
  if(lab)lab.textContent=fp.branch||'branch';
}
async function loadOideBranches(){
  const list=$('oideBranchList');if(!list)return;
  try{
    const d=await api('/api/git/branches').then(r=>r.json());
    const branches=d.branches||[];
    const cur=d.current||(window._openideFingerprint||{}).branch||'';
    window._oideBranches=branches;
    if(!d.ok||!branches.length){
      list.innerHTML='<div class="og-empty">No branches available</div>';
      return;
    }
    list.innerHTML=branches.map(b=>{
      const on=b===cur?' on':'';
      return `<button type="button" class="og-branch${on}" data-branch="${esc(b)}" onclick="checkoutOideBranch(${JSON.stringify(b)})"><span>${esc(b)}</span>${b===cur?'<span class="og-hint">current</span>':''}</button>`;
    }).join('');
  }catch(e){
    list.innerHTML='<div class="og-empty">No branches available</div>';
  }
}
function filterOideBranchMenu(q){
  const needle=(q||'').toLowerCase().trim();
  document.querySelectorAll('#oideBranchList .og-branch').forEach(btn=>{
    const name=(btn.dataset.branch||btn.textContent||'').toLowerCase();
    btn.style.display=!needle||name.includes(needle)?'':'none';
  });
}
async function checkoutOideBranch(branch){
  closeAllOideGlassMenus();
  openideSetStatus('Checking out '+branch+'…',true);
  try{
    const r=await api('/api/git/checkout',{method:'POST',body:JSON.stringify({branch})});
    if(r.ok){
      if(r.fingerprint)window._openideFingerprint=r.fingerprint;
      syncOideBranchLabel();
      toast('Branch: '+branch);
      refreshOpenIDEFingerprint();
      loadOpenIDEGitBundle();
    }else toast(r.error||'Checkout failed');
  }catch(e){toast('Checkout failed')}
  openideSetStatus('',false);
}
function loadOpenIDERuns(){
  try{
    const raw=JSON.parse(localStorage.getItem('airgpt_oide_runs')||'[]');
    return Array.isArray(raw)?raw.slice(0,80):[];
  }catch(e){return[]}
}
function saveOpenIDERuns(){
  try{localStorage.setItem('airgpt_oide_runs',JSON.stringify((window._openideRuns||[]).slice(0,80)))}catch(e){}
}
function syncOpenIDEAgentTabs(){
  const tabs=$('openideOpenTabs');if(!tabs)return;
  const runs=(window._openideRuns||[]).slice(0,12);
  const keep=[...tabs.querySelectorAll('.openide-open-tab')].filter(t=>t.dataset.tab==='file'||t.dataset.tab==='browser');
  tabs.innerHTML='';
  const agent=document.createElement('div');
  agent.className='openide-open-tab on';
  agent.dataset.tab='agent';
  agent.innerHTML='<span>Agent</span>';
  agent.onclick=function(){openideSelectOpenTab(this)};
  tabs.appendChild(agent);
  runs.forEach((r,i)=>{
    const el=document.createElement('div');
    el.className='openide-open-tab';
    el.dataset.tab='agent-run';
    el.dataset.run=String(i);
    el.title=r.prompt||'Agent';
    el.innerHTML=`<span>${esc((r.prompt||'Agent').slice(0,28))}</span>`;
    el.onclick=function(){
      openideSelectOpenTab(this);
      openideFocusRun(r.repo||'',i);
    };
    tabs.appendChild(el);
  });
  keep.forEach(k=>tabs.appendChild(k));
}
function newOpenIDECortexRun(repoPath){
  $('oideNewCortexBtn')?.classList.add('on');
  setOpenIDEView('agents');
  if(repoPath){
    const cur=($('openideRoot')?.getAttribute('title')||'').trim();
    if(cur!==repoPath){
      window._openidePendingNewAgent=true;
      openIDEWorkspace(repoPath);
      return;
    }
  }
  const hasWs=hasOpenIDEWorkspace();
  if(hasWs){
    openideShowEmptyHint(true,'slim');
    $('openidePrompt')?.focus();
  }else{
    openideShowEmptyHint(true);
  }
  syncOpenIDEAgentTabs();
  const tabs=$('openideOpenTabs');
  if(tabs){
    document.querySelectorAll('#openideOpenTabs .openide-open-tab').forEach(x=>x.classList.remove('on'));
    const ag=[...tabs.querySelectorAll('.openide-open-tab')].find(t=>t.dataset.tab==='agent');
    if(ag)ag.classList.add('on');
  }
  toast(hasWs?'New Agent — describe what to build':'New Agent — open a folder or Create app');
}
function hasOpenIDEWorkspace(){
  const root=($('openideRoot')?.getAttribute('title')||$('openideRoot')?.textContent||'').trim();
  return !!(root&&root!=='No workspace');
}
function openideEmptyHintHtml(kind){
  if(kind==='slim'){
    return `<h3>Describe what to build</h3>
      <div class="oide-empty-sub">Type below and press Run — or Create app for a scaffold first.</div>
      <div class="openide-empty-ctas">
        <button type="button" class="primary" onclick="openideCreateApp()">Create app</button>
        <button type="button" onclick="$('openidePrompt')?.focus()">Type prompt</button>
      </div>`;
  }
  return `<h3>Create an app</h3>
    <div class="oide-empty-sub">One prompt → scaffold → Cortex finishes it. Share on LAN like a Doc.</div>
    <div class="openide-empty-ctas">
      <button type="button" class="primary" onclick="openideCreateApp()">Create app</button>
      <button type="button" onclick="openideShareLanApp()">Share LAN</button>
      <button type="button" onclick="openKeyVault({banner:'OpenVault Key Vault — enable OpenFree or paste a free key'})">Keys</button>
      <button type="button" onclick="openIDEWorkspace()">Browse</button>
      <button type="button" onclick="openideNewFolder()">New folder</button>
      <button type="button" onclick="openideGithubRepo()">GitHub</button>
      <button type="button" onclick="openideAutoRepos()">Auto repos</button>
    </div>`;
}
function openideShowEmptyHint(show,kind){
  const t=$('openideTranscript');if(!t)return;
  let hint=$('openideEmptyHint');
  if(!show){
    if(hint)hint.style.display='none';
    return;
  }
  if(!hint){
    hint=document.createElement('div');
    hint.className='openide-empty-hint';
    hint.id='openideEmptyHint';
    t.insertBefore(hint,$('openideDiff')||t.firstChild);
  }
  hint.innerHTML=openideEmptyHintHtml(kind||(hasOpenIDEWorkspace()?'slim':''));
  hint.style.display='';
}
function openidePromptKeydown(event){
  if(event.key!=='Enter')return;
  if(event.shiftKey)return;
  if(event.isComposing)return;
  event.preventDefault();
  runOpenIDEAgent();
}
async function openideConnectOpenVault(){
  openideSetStatus('Connecting OpenVault…',true);
  try{
    const resp=await api('/api/openvault/connect',{method:'POST',body:JSON.stringify({name:'AirGPT OpenIDE',auto_approve:true})});
    const r=await resp.json();
    if(r&&r.ok){
      openideSetStatus(r.approved?'OpenVault connected':'OpenVault handshake pending',false);
      toast(r.approved?'OpenVault mesh · approved':'Approve OpenIDE at http://127.0.0.1:5000/#mesh');
      return r;
    }
    openideSetStatus('OpenVault offline',false);
    toast((r&&r.error)||(r&&r.hint)||'OpenVault not reachable on :5000');
  }catch(e){
    openideSetStatus('OpenVault connect failed',false);
    toast('Restart AirGPT to load OpenVault bridge, then retry');
  }
}
async function openideShareLanApp(){
  /** Publish current scaffold/app to OpenVault Small Software LAN cloud */
  const title=($('openideSessionTitle')?.textContent||'Shared app').trim()||'Shared app';
  const path=($('openideRoot')?.getAttribute('title')||'').trim();
  openideSetStatus('Sharing on LAN cloud…',true);
  try{
    const r=await fetch('http://127.0.0.1:5000/api/cloud/shares',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({title,source_path:path,owner:'openide',summary:'Shared from OpenIDE Create-App',visibility:'lan',env_edge:{PORT:'5173'}})
    }).then(x=>x.json());
    if(r&&r.ok&&r.share){
      openideSetStatus('Shared · code '+r.share.share_code,false);
      toast('LAN share code: '+r.share.share_code+' (OpenVault cloud)');
      openideAppendTranscript(`<div class="openide-help"><strong>LAN share</strong>
        <p>Code <code>${esc(r.share.share_code)}</code> · peers on your LAN can pull this Small Software app.</p>
        <p>Bypass/force flags are denied by OpenVault firewall (WARN + cannot).</p></div>`);
      return r;
    }
    const detail=(r&&r.detail)||r;
    toast('Share blocked — check OpenVault firewall');
    openideSetStatus('Share denied',false);
    console.warn('share',detail);
  }catch(e){
    openideSetStatus('Share failed',false);
    toast('OpenVault :5000 required for LAN share');
  }
}
async function openideCreateApp(){
  if(!(await openideEnsureKeys())){
    window._openidePendingCreateApp=true;
    return;
  }
  let prompt=($('openidePrompt')?.value||'').trim();
  if(!prompt){
    prompt=window.prompt('Describe the app to create (one prompt)', 'A local todo app with filters and dark theme');
    if(!prompt)return;
    if($('openidePrompt'))$('openidePrompt').value=prompt;
  }
  openideSetStatus('Scaffolding app…',true);
  openideShowEmptyHint(false);
  try{
    const resp=await api('/api/openide/scaffold',{method:'POST',body:JSON.stringify({prompt,template:'auto',parent:'apps'})});
    const r=await resp.json();
    if(!r||!r.ok){
      openideSetStatus(r?.error||'Scaffold failed',false);
      toast(r?.error||'Scaffold failed');
      openideShowEmptyHint(true);
      return;
    }
    if(r.workspace_root)rememberOideWorkspace(r.workspace_root,r.workspace_name||'');
    toast('Scaffolded '+r.app_path+' · '+r.template);
    openideAppendTranscript(`<div class="openide-help"><strong>App scaffolded · ${esc(r.app_path)}</strong>
      <p>Template <code>${esc(r.template)}</code> · Run with <code>${esc(r.run_hint||'')}</code></p>
      <p>Cortex will complete your intent next. Preview: ${esc(r.preview_hint||'')}</p>
      <ol><li>Approve file writes as they appear</li><li>Start the app with the run hint</li><li>Open Browser tab to preview</li></ol>
    </div>`);
    if($('openidePrompt'))$('openidePrompt').value=r.seed_prompt||prompt;
    if(r.preview_hint){
      const inp=$('openidePreviewUrl');if(inp)inp.value=r.preview_hint;
    }
    openOpenIDERightRail();
    openideWorkTab('browser');
    refreshOpenIDETree(r.app_path);
    setOideMode('plan');
    window._openideThinkMode='deep';
    await runOpenIDEAgent({prompt:r.seed_prompt||prompt,fromScaffold:true});
  }catch(e){
    openideSetStatus('Scaffold failed',false);
    toast('Scaffold failed');
    openideShowEmptyHint(true);
  }
}
function renderOpenIDERepos(){
  const host=$('openideRepoList');if(!host)return;
  const rec=oideWsRecents();
  const cur=($('openideRoot')?.getAttribute('title')||$('openideRoot')?.textContent||'').trim();
  if(!rec.length){
    host.innerHTML=`<div class="empty" style="padding:6px;font-size:11px;color:var(--muted)">No repositories yet</div>
      <button type="button" class="openide-browse-link" onclick="openIDEWorkspace()">Browse folder…</button>`;
    return;
  }
  host.innerHTML=rec.map(r=>{
    const on=cur&&(cur===r.path||cur.endsWith(r.name))?' on':'';
    const runs=(window._openideRuns||[]).filter(x=>{
      if(x.repo&&(x.repo===r.path||x.repo.endsWith(r.name)))return true;
      return !x.repo&&!!on;
    });
    const runBits=runs.length
      ?runs.slice(0,8).map((x,i)=>`<div class="openide-run-item${i===0&&on?' on':''}" title="${esc(x.prompt||'')}" onclick="event.stopPropagation();openideFocusRun(${JSON.stringify(r.path)},${i})"><span class="or-title">${esc((x.prompt||'Agent').slice(0,36))}</span><span class="or-when">${esc(x.when||'')}</span></div>`).join('')
      :'<div class="empty" style="padding:2px 8px;font-size:10px;color:var(--muted)">No agents yet</div>';
    return `<div class="openide-repo-group">
      <div class="openide-repo-hd${on}" onclick="openIDEWorkspace(${JSON.stringify(r.path)})" title="${esc(r.path)}">
        <span>${esc(r.name||r.path)}</span>
        <span class="repo-plus" onclick="event.stopPropagation();newOpenIDECortexRun(${JSON.stringify(r.path)})" title="New Agent in this repo">+</span>
      </div>
      <div class="openide-repo-agents">${runBits}</div>
    </div>`;
  }).join('')+`<button type="button" class="openide-browse-link" onclick="openIDEWorkspace()">Browse folder…</button>`;
  const lab=$('openideOnWsLabel');
  if(lab){
    const name=rec.find(r=>cur&&(cur===r.path||cur.endsWith(r.name)))?.name||folderNameFromRoot(cur)||'AirGPT';
    lab.textContent='On '+name;
  }
}
function openideFocusRun(repoPath,idx){
  const cur=($('openideRoot')?.getAttribute('title')||'').trim();
  if(repoPath&&cur&&cur!==repoPath){
    window._openidePendingNewAgent=true;
    openIDEWorkspace(repoPath);
    return;
  }
  setOpenIDEView('agents');
  const hint=$('openideEmptyHint');if(hint)hint.style.display='none';
  $('openidePrompt')?.focus();
  const runs=(window._openideRuns||[]).filter(x=>{
    if(!repoPath)return true;
    if(x.repo&&(x.repo===repoPath||x.repo.endsWith(repoPath.split(/[/\\]/).pop()||'')))return true;
    return !x.repo;
  });
  const r=runs[idx]||(window._openideRuns||[])[idx];
  if(r&&r.prompt&&$('openidePrompt')&&!$('openidePrompt').value)$('openidePrompt').placeholder='Continue: '+(r.prompt||'').slice(0,60);
}
function folderNameFromRoot(p){
  return String(p||'').split(/[/\\]/).filter(Boolean).pop()||'';
}
async function openideNewFolder(){
  const parent=prompt('Parent directory (absolute)',info.workspace_root||'D:\\\\');
  if(!parent)return;
  const name=prompt('New folder name','my-project');
  if(!name)return;
  const sep=String(parent).includes('/')?'/':'\\\\';
  const path=String(parent).replace(/[\\/]+$/,'')+sep+name;
  openideSetStatus('Creating folder…',true);
  const isWin=/^[A-Za-z]:[\\/]/.test(path)||path.includes('\\\\');
  const cmd=isWin?('powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '+JSON.stringify(path)+'"'):('mkdir -p '+JSON.stringify(path));
  const r=await runOpenIDECmdRaw(cmd);
  openideSetStatus(r.ok?'Folder created':'Create failed',false);
  if(!r.ok){toast((r.stderr||r.error||'mkdir failed').slice(0,120));return}
  await openIDEWorkspace(path);
}
async function openideGithubRepo(){
  const url=prompt('GitHub repository URL (https://github.com/org/repo)\nWe clone locally and can help push under a netie.ai account — we never type your credentials.');
  if(!url)return;
  if(!/github\.com[:/]/i.test(url)){toast('Paste a GitHub URL');return}
  openideSetStatus('Checking GitHub auth…',true);
  const auth=await runOpenIDECmdRaw('gh auth status');
  if(!auth.ok){
    openideSetStatus('GitHub auth needed',false);
    openideAppendTranscript(`<div class="openide-help"><strong>GitHub auth</strong>
      <p>Install/login with <code>gh auth login</code>, or paste a clone URL after you have access.
      AirGPT / netie.ai never creates accounts or types credentials for you.</p>
      <button type="button" class="btn" onclick="runOpenIDECmdRaw('gh auth login').then(()=>toast('Follow terminal for gh login'))">Run gh auth login</button>
    </div>`);
    openOpenIDERightRail();openideWorkTab('terminal');
    return;
  }
  const destParent=prompt('Clone into folder',info.workspace_root||'D:\\\\AirGPT');
  if(!destParent)return;
  const slug=(url.replace(/\.git$/,'').split('/').filter(Boolean).pop()||'repo');
  const dest=String(destParent).replace(/[\\/]+$/,'')+(String(destParent).includes('/')?'/':'\\\\')+slug;
  openideSetStatus('Cloning…',true);
  openOpenIDERightRail();openideWorkTab('terminal');
  const clone=await runOpenIDECmdRaw('git clone '+JSON.stringify(url)+' '+JSON.stringify(dest));
  openideSetStatus(clone.ok?'Cloned':'Clone failed',false);
  if(clone.ok){
    toast('Cloned · opening workspace');
    await openIDEWorkspace(dest);
  }else toast((clone.stderr||clone.error||'clone failed').slice(0,120));
}
function openideAutoRepos(){
  renderOpenIDERepos();
  const n=oideWsRecents().length;
  toast(n?('Found '+n+' recent repo(s)'):'No recents — Browse or GitHub first');
  $('oideNewCortexBtn')?.classList.add('on');
}
function updateOpenIDEOnWsStat(){
  const el=$('openideOnWsStat');if(!el)return;
  const plus=window._openidePlus||0,minus=window._openideMinus||0;
  el.innerHTML=plus||minus?`<span class="plus">+${plus}</span> <span class="minus">-${minus}</span>`:'Changes · clean';
}
function bindOpenIDEResizers(){
  const shell=$('openideShell');if(!shell)return;
  const bind=(el,which)=>{
    if(!el||el.dataset.bound==='1')return;
    el.dataset.bound='1';
    el.addEventListener('pointerdown',e=>{
      e.preventDefault();
      el.classList.add('dragging');
      el.setPointerCapture?.(e.pointerId);
      const startX=e.clientX;
      const rect=shell.getBoundingClientRect();
      const cs=getComputedStyle(shell);
      const leftPx=parseFloat(cs.getPropertyValue('--oide-left'))||220;
      let rightRaw=cs.getPropertyValue('--oide-right').trim()||'36%';
      let rightPx=rightRaw.endsWith('%')?(parseFloat(rightRaw)/100)*rect.width:parseFloat(rightRaw)||rect.width*0.36;
      const onMove=ev=>{
        const dx=ev.clientX-startX;
        if(which==='left'){
          const next=Math.max(160,Math.min(420,leftPx+dx));
          shell.style.setProperty('--oide-left',next+'px');
          localStorage.setItem('airgpt_oide_left',next+'px');
        }else{
          const next=Math.max(240,Math.min(rect.width*0.55,rightPx-dx));
          shell.style.setProperty('--oide-right',next+'px');
          localStorage.setItem('airgpt_oide_right',next+'px');
        }
      };
      const onUp=()=>{
        el.classList.remove('dragging');
        window.removeEventListener('pointermove',onMove);
        window.removeEventListener('pointerup',onUp);
      };
      window.addEventListener('pointermove',onMove);
      window.addEventListener('pointerup',onUp);
    });
  };
  bind($('openideSplitLeft'),'left');
  bind($('openideSplitRight'),'right');
  const termSplit=$('openideTermSplit'),termWrap=$('openideTermWrap');
  if(termSplit&&termWrap&&termSplit.dataset.bound!=='1'){
    termSplit.dataset.bound='1';
    const savedT=localStorage.getItem('airgpt_oide_term');
    if(savedT)termWrap.style.setProperty('--oide-term',savedT);
    termSplit.addEventListener('pointerdown',e=>{
      e.preventDefault();
      termSplit.classList.add('dragging');
      const startY=e.clientY;
      const startH=termWrap.getBoundingClientRect().height;
      const onMove=ev=>{
        const next=Math.max(72,Math.min(320,startH+(startY-ev.clientY)));
        termWrap.style.setProperty('--oide-term',next+'px');
        localStorage.setItem('airgpt_oide_term',next+'px');
      };
      const onUp=()=>{
        termSplit.classList.remove('dragging');
        window.removeEventListener('pointermove',onMove);
        window.removeEventListener('pointerup',onUp);
      };
      window.addEventListener('pointermove',onMove);
      window.addEventListener('pointerup',onUp);
    });
  }
}
function renderOpenIDEAppChips(){
  const host=$('openideAppChips');if(!host)return;
  const apps=[
    {id:'dms-ui',label:'dms-ui:3000',url:'http://127.0.0.1:3000/'},
    {id:'dms-v3',label:'dms-v3:6010',url:'http://127.0.0.1:6010/'},
    {id:'openfree',label:'openfree:20128',url:'http://127.0.0.1:20128/'},
    {id:'cortex',label:'cortex:8010',url:'http://127.0.0.1:8010/'},
  ];
  try{
    const extra=JSON.parse(localStorage.getItem('airgpt_openide_apps')||'[]');
    if(Array.isArray(extra))extra.forEach(a=>{if(a&&a.url)apps.push(a)});
  }catch(e){}
  // Do not preselect AirGPT — nesting this app traps navigation
  host.innerHTML=apps.map(a=>`<button type="button" class="openide-app-chip" data-url="${esc(a.url)}" onclick="openideSelectApp(this)"><span class="play">▶</span>${esc(a.label||a.url)}</button>`).join('');
}
function openideSelectApp(btn){
  document.querySelectorAll('.openide-app-chip').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  const u=btn.dataset.url||'';
  if(/127\.0\.0\.1:8765|localhost:8765/i.test(u)){
    toast('AirGPT stays outside the preview — use ← Home');
    return;
  }
  openideLoadPreview(u);
}
function openideLoadPreview(url){
  const u=(url||'').trim();if(!u)return;
  if(/127\.0\.0\.1:8765|localhost:8765/i.test(u)){toast('Cannot nest AirGPT in preview');return}
  const inp=$('openidePreviewUrl');if(inp)inp.value=u;
  const frame=$('openidePreviewFrame');if(frame)frame.src=u;
}
function openideAppendTranscript(html){
  const t=$('openideTranscript');if(!t)return;
  const hint=$('openideEmptyHint');
  if(hint)hint.style.display='none';
  const wrap=document.createElement('div');
  wrap.innerHTML=html;
  while(wrap.firstChild)t.insertBefore(wrap.firstChild,$('openideDiff')||null);
  t.scrollTop=t.scrollHeight;
}
function openideAppendThought(text,ms){
  const label=ms?`Thought · ${Math.round(ms/100)/10}s`:'Thought';
  openideAppendTranscript(`<details class="openide-thought"><summary>${esc(label)}</summary><pre>${esc(text||'')}</pre></details>`);
}
function openideSetStatus(text,live){
  const el=$('openideStatus');if(el)el.textContent=text||'';
  const dot=$('openideLiveDot');if(dot)dot.style.opacity=live?1:.35;
}
function renderOpenIDERunsList(){
  const host=$('openideRunsList');if(!host)return;
  const runs=window._openideRuns||[];
  if(!runs.length){host.innerHTML='<div class="empty" style="padding:10px;font-size:12px;color:var(--muted)">No runs yet</div>';return}
  host.innerHTML=runs.slice(0,40).map((r,i)=>{
    const st=(r.status||'').toLowerCase();
    const need=st==='error'||st==='failed'||st==='needs_input'||!!r.needs_input;
    const n=need?Math.max(1,Number(r.need_count)||1):0;
    const dotCls=need?'openide-run-dot need':'openide-run-dot';
    const dn=need?` data-n="${n}"`:'';
    return `<div class="openide-run-item${i===0?' on':''}" onclick="this.parentNode.querySelectorAll('.openide-run-item').forEach(x=>x.classList.remove('on'));this.classList.add('on')">
    <span class="${dotCls}"${dn} title="${need?'Needs input':'Complete'}"></span>
    <div>${esc((r.prompt||'Run').slice(0,48))}</div>
    <div class="or-meta">${esc(r.status||'')} · ${esc(r.mode||'')} · ${esc(r.when||'')}</div>
  </div>`;
  }).join('');
}
async function refreshOpenIDEFingerprint(){
  try{
    const fp=await api('/api/git/fingerprint?light=1').then(r=>r.json());
    if(fp&&fp.ok){
      window._openideFingerprint=fp;
      const st=$('openideStatus');
      if(st&&!st.textContent.includes('Agent')){
        st.textContent=`${fp.branch||'detached'}@${(fp.head||'').slice(0,7)} · ${fp.dirty_count||0} dirty`;
      }
    }
  }catch(e){}
}
async function loadOpenIDEGitBundle(){
  const el=$('openideDiffStat');const btn=$('openideCreatePr');const gitEl=$('openideGit');
  try{
    const bundle=await api('/api/git/summary').then(r=>r.json());
    if(!bundle||!bundle.ok)throw new Error('summary failed');
    const fp=bundle.fingerprint||{};
    window._openideFingerprint=fp;
    window._openidePlus=bundle.plus||0;window._openideMinus=bundle.minus||0;
    const plus=window._openidePlus,minus=window._openideMinus;
    if(el)el.innerHTML=plus||minus?`<span class="plus">+${plus}</span><span class="minus">-${minus}</span>`:'';
    updateOpenIDEOnWsStat();
    syncOideBranchLabel();
    const dirty=(fp.dirty_count||0)>0||plus||minus;
    if(btn){
      btn.disabled=!dirty;
      btn.classList.toggle('show',!!dirty);
    }
    const st=bundle.status||{};
    const diff=bundle.diff||{};
    if($('openideStatus')&&!($('openideStatus').textContent||'').includes('Agent')){
      $('openideStatus').textContent=`${fp.branch||'detached'}@${(fp.head||'').slice(0,7)} · ${fp.dirty_count||0} dirty`;
    }
    if(gitEl){
      gitEl.innerHTML=`<div class="openide-git-toolbar">
      <button type="button" class="btn" onclick="openideGitFetch()">Fetch latest</button>
      <button type="button" class="btn" onclick="loadOpenIDEGitBundle()">Refresh</button>
      <button type="button" class="btn" onclick="runOpenIDECmdRaw('git worktree list').then(r=>{const t=$('openideTerm');if(t)t.textContent=(r.stdout||r.error||'')})">Worktrees</button>
    </div>
    <div class="hint" style="padding:6px 8px">${esc(fp.branch||'?')} @ ${esc((fp.head||'').slice(0,12))} · dirty ${fp.dirty_count||0}</div>
    <pre style="white-space:pre-wrap;margin:0;padding:6px">${esc(st.stdout||st.error||st.stderr||'')}</pre>
    <pre style="white-space:pre-wrap;margin-top:8px;opacity:.85;padding:6px">${esc((fp.log||'').slice(0,1200))}</pre>
    <pre style="white-space:pre-wrap;margin-top:8px;opacity:.75;padding:6px">${esc((diff.stdout||diff.error||'').slice(0,4000))}</pre>`;
    }
  }catch(e){
    if(el)el.textContent='';
    if(btn){btn.disabled=true;btn.classList.remove('show')}
    if(gitEl)gitEl.innerHTML='<div class="empty">Git unavailable</div>';
  }
}
async function refreshOpenIDEDiffStat(){return loadOpenIDEGitBundle()}
async function openideCreatePR(){
  openideSetStatus('Preparing PR…',true);
  try{
    const msg=prompt('Commit message','OpenIDE changes');
    if(!msg){openideSetStatus('PR cancelled',false);return}
    const add=await runOpenIDECmdRaw('git add -A');
    if(!add.ok&&add.error){toast(add.error);openideSetStatus('git add failed',false);return}
    // Prefer simple -m without shell metacharacters
    const safe=msg.replace(/["\\]/g,'').slice(0,120);
    const commit=await runOpenIDECmdRaw('git commit -m "'+safe+'"');
    if(!commit.ok){
      openideSetStatus('Commit failed (nothing to commit?)',false);
      toast((commit.stderr||commit.error||'commit failed').slice(0,120));
      return;
    }
    const r=await runOpenIDECmdRaw('gh pr create --fill');
    openideSetStatus(r.ok?'PR created':'Committed — open PR in GitHub (gh missing?)',false);
    toast(r.ok?'PR created':((r.error||r.stderr||'Committed locally').slice(0,100)));
    refreshOpenIDEDiffStat();refreshOpenIDEGit();
  }catch(e){openideSetStatus('PR failed',false);toast('PR failed')}
}
async function runOpenIDECmdRaw(cmd){
  try{
    return await api('/api/terminal/exec',{method:'POST',body:JSON.stringify({cmd,session_id:terminalSessionId})});
  }catch(e){return{ok:false,error:String(e)}}
}
async function refreshOpenIDEGit(){return loadOpenIDEGitBundle()}
async function openideGitFetch(){
  openideSetStatus('Fetching…',true);
  const r=await runOpenIDECmdRaw('git fetch --all --prune');
  openideSetStatus(r.ok?'Fetched':'Fetch failed',false);
  window._openideFetchContext=((r.stdout||'')+(r.stderr||'')).slice(0,2000);
  refreshOpenIDEGit();refreshOpenIDEFingerprint();
  toast(r.ok?'Fetched — next Run includes latest context':'Fetch failed');
}
async function openIDEWorkspace(presetPath){
  const p=presetPath||prompt('Absolute path to project folder',info.workspace_root||'D:\\\\AirGPT');
  if(!p)return;
  try{
    const r=await api('/api/workspace/open',{method:'POST',body:JSON.stringify({path:p})});
    if(r.ok){
      rememberOideWorkspace(r.root||p,r.name||'');
      toast('Workspace opened');
      showOpenIDEPage();
    }else toast(r.error||'Failed');
  }catch(e){toast('Open failed')}
}
async function refreshOpenIDETree(rel){
  const tree=$('openideTree');if(!tree)return;
  try{
    const q=rel?('?path='+encodeURIComponent(rel)):'';
    const d=await api('/api/fs/tree'+q).then(r=>r.json());
    if(!d.ok){tree.innerHTML='<div class="empty">'+esc(d.error||'no workspace')+'</div>';return}
    tree.innerHTML='';
    function addNode(e,depth){
      const row=document.createElement('div');
      row.className='fe';
      row.style.paddingLeft=(depth*10)+'px';
      row.textContent=(e.type==='dir'?'📁 ':'📄 ')+e.name;
      row.title=e.path||'';
      if(e.type==='dir'){
        row.onclick=()=>refreshOpenIDETree(e.path);
      }else{
        row.onclick=()=>openIDEFile(e.path);
      }
      tree.appendChild(row);
      (e.children||[]).forEach(c=>addNode(c,depth+1));
    }
    (d.entries||[]).forEach(e=>addNode(e,0));
    if(!(d.entries||[]).length)tree.innerHTML='<div class="empty">Empty</div>';
  }catch(e){tree.innerHTML='<div class="empty">Tree error</div>'}
}
async function openIDEFile(path){
  openideFile=path;
  const shell=$('openideShell');
  if(shell&&!shell.classList.contains('openide-view-editor'))setOpenIDEView('editor');
  else openideWorkTab('editor');
  // Mirror into Open Tabs
  const tabs=$('openideOpenTabs');
  if(tabs&&path){
    const name=path.split(/[/\\]/).pop();
    let el=[...tabs.querySelectorAll('.openide-open-tab')].find(t=>t.dataset.path===path);
    if(!el){
      el=document.createElement('div');
      el.className='openide-open-tab';
      el.dataset.tab='file';
      el.dataset.path=path;
      el.innerHTML=`<span>${esc(name)}</span>`;
      el.onclick=function(){openideSelectOpenTab(this);openIDEFile(path)};
      tabs.appendChild(el);
    }
    document.querySelectorAll('#openideOpenTabs .openide-open-tab').forEach(x=>x.classList.remove('on'));
    el.classList.add('on');
  }
  try{
    const d=await api('/api/fs/read?path='+encodeURIComponent(path)).then(r=>r.json());
    const el=$('openideEditor');if(!el)return;
    if(window.openideMonaco&&typeof openideMonaco.dispose==='function'){
      try{openideMonaco.dispose()}catch(e){}
      openideMonaco=null;
    }
    el.innerHTML='';
    if(window.require){
      require.config({paths:{vs:'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs'}});
      require(['vs/editor/editor.main'],function(){
        const host=$('openideEditor');if(!host)return;
        openideMonaco=monaco.editor.create(host,{value:d.content||d.error||'',language:'plaintext',theme:'vs-dark',automaticLayout:true});
      });
    }else{
      el.innerHTML=`<pre id="openidePre"></pre>`;
      const pre=$('openidePre');if(pre)pre.textContent=d.content||d.error||'';
    }
  }catch(e){toast('Read failed')}
}
async function openideMentionPicker(el){
  const pick=$('openideMentionPick');if(!pick||!el)return;
  const val=el.value||'';
  const at=val.lastIndexOf('@');
  if(at<0){pick.style.display='none';return}
  const q=val.slice(at+1).split(/\s/)[0];
  if(q.includes(' ')||q.length>80){pick.style.display='none';return}
  clearTimeout(window._openideMentionT);
  await new Promise(r=>window._openideMentionT=setTimeout(r,160));
  if(($('openidePrompt')?.value||'')!==val)return; // stale
  try{
    const d=await api('/api/fs/find?q='+encodeURIComponent(q)).then(r=>r.json());
    const matches=(d.matches||[]).slice(0,12);
    if(!matches.length){pick.style.display='none';return}
    pick.style.display='block';
    pick.innerHTML='';
    matches.forEach(m=>{
      const b=document.createElement('button');
      b.type='button';b.className='btn';b.style.cssText='display:block;width:100%;text-align:left;border-radius:0;font-size:11px';
      b.textContent=m.path;b.onclick=()=>{
        el.value=val.slice(0,at)+'@'+m.path+' ';
        pick.style.display='none';el.focus();
      };
      pick.appendChild(b);
    });
  }catch(e){pick.style.display='none'}
}
function renderOpenIDEApproval(ev){
  const box=$('openideDiff');if(!box)return;
  window._openidePendingWrite=ev;
  const mode=ev.mode||'write';
  const preview=mode==='patch'
    ? `--- old ---\n${(ev.old||'').slice(0,2000)}\n+++ new ---\n${(ev.new||'').slice(0,2000)}`
    : (ev.content||'').slice(0,4000);
  openideAppendTranscript(`<div class="openide-tool-line"><span class="ot-ico">✎</span><span>Write preview · <strong>${esc(ev.path||'')}</strong> (${esc(mode)})</span></div>`);
  const card=`<div class="openide-approval"><strong style="color:var(--text)">${esc(ev.path||'')} · ${esc(mode)}</strong>
    <pre>${esc(preview)}</pre>
    <div style="display:flex;gap:8px;margin-top:8px">
      <button type="button" class="btn primary" onclick="approveOpenIDEWrite()">Approve</button>
      <button type="button" class="btn" onclick="rejectOpenIDEWrite()">Reject</button>
    </div></div>`;
  box.innerHTML=card;
  const stack=$('openideChangesStack'),empty=$('openideChangesEmpty');
  if(stack){stack.innerHTML=card;if(empty)empty.style.display='none'}
  openideRightTab('changes');
  $('openideTranscript')?.scrollTo({top:1e9,behavior:'smooth'});
  refreshOpenIDEDiffStat();
}
async function approveOpenIDEWrite(){
  const p=window._openidePendingWrite;if(!p||!p.path)return toast('Nothing to approve');
  try{
    let r;
    if(p.mode==='patch'){
      r=await api('/api/fs/patch',{method:'POST',body:JSON.stringify({path:p.path,old:p.old||'',new:p.new||'',apply:true})});
    }else{
      r=await api('/api/fs/write',{method:'POST',body:JSON.stringify({path:p.path,content:p.content||'',apply:true})});
    }
    toast(r.ok?'Approved & applied':'Apply failed');
    if(r.ok){
      openIDEFile(p.path);refreshOpenIDEGit();window._openidePendingWrite=null;
      const box=$('openideDiff');if(box)box.innerHTML='<span class="hint">Applied.</span>';
      const stack=$('openideChangesStack'),empty=$('openideChangesEmpty');
      if(stack)stack.innerHTML='';if(empty)empty.style.display='';
    }
  }catch(e){toast('Approve failed')}
}
function rejectOpenIDEWrite(){
  window._openidePendingWrite=null;
  const box=$('openideDiff');if(box)box.innerHTML='<span class="hint">Rejected — disk unchanged.</span>';
  const stack=$('openideChangesStack'),empty=$('openideChangesEmpty');
  if(stack)stack.innerHTML='';if(empty)empty.style.display='';
  toast('Rejected');
}
async function openideEnsureKeys(){
  const backend='local';
  try{
    const cache=window._openideReadyCache;
    if(cache&&cache.backend===backend&&(performance.now()-cache.t)<30000){
      if(cache.ok)return true;
    }
    const r=await api('/api/openide/ready?backend='+encodeURIComponent(backend)).then(x=>x.json());
    window._openideReadyCache={backend,ok:!!(r&&r.ok),t:performance.now()};
    if(r&&r.ok)return true;
    const hint=(r&&r.hint)||'Need a key to Run — enable OpenFree or paste a free-tier key, then retry.';
    window._openidePendingRun=true;
    await openKeyVault({banner:hint});
    toast(hint);
    return false;
  }catch(e){
    toast('Couldn’t check keys — is AirGPT running on this PC?');
    return false;
  }
}
async function continueOpenIDEAgent(){
  const prompt=($('openidePrompt')?.value||'').trim()||'Continue from the previous step.';
  return runOpenIDEAgent({resume:true,prompt});
}
async function runOpenIDEAgent(opts){
  opts=opts||{};
  const prompt=(opts.prompt||($('openidePrompt')?.value||'')).trim();
  if(!prompt)return toast('Enter a task');
  // Create-app magic: no workspace + looks like build intent → scaffold first
  if(!opts.fromScaffold&&!opts.resume&&!hasOpenIDEWorkspace()&&/\b(build|create|make|scaffold|app|website|todo)\b/i.test(prompt)){
    if($('openidePrompt'))$('openidePrompt').value=prompt;
    return openideCreateApp();
  }
  if(!opts.fromScaffold&&!hasOpenIDEWorkspace()){
    toast('Open a folder or Create app first');
    openideShowEmptyHint(true);
    return;
  }
  if(!(await openideEnsureKeys()))return;
  openideShowEmptyHint(false);
  $('oideNewCortexBtn')?.classList.remove('on');
  const diffBox=$('openideDiff');if(diffBox)diffBox.innerHTML='';
  window._openidePendingWrite=null;
  const mode=window._openideThinkMode||'deep';
  const backend='local';
  const repoPath=($('openideRoot')?.getAttribute('title')||$('openideRoot')?.textContent||'').trim();
  openideAppendTranscript(`<div class="openide-msg user">${esc(prompt)}</div>`);
  openideAppendTranscript(`<div class="openide-tool-line" id="openideRunningLine"><span class="ot-ico">◐</span><span>Running agent…</span></div>`);
  openideSetStatus('Agent working…',true);
  if($('openidePrompt')&&!opts.resume)$('openidePrompt').value='';
  window._openideRuns=[...(window._openideRuns||[])];
  window._openideRuns.unshift({prompt,status:'running',mode,when:new Date().toLocaleTimeString(),repo:repoPath});
  saveOpenIDERuns();
  renderOpenIDERunsList();
  renderOpenIDERepos();
  syncOpenIDEAgentTabs();
  let toolCount=0,thoughtBuf='',thoughtT0=performance.now();
  try{
    let aid=window._openideCodeAgentId;
    if(!aid){
      const agents=(await api('/api/agents').then(r=>r.json())).agents||[];
      let code=agents.find(a=>(a.name||'')==='Code Agent');
      aid=code?.id;
      if(!aid){
        await api('/api/agents',{method:'POST',body:JSON.stringify({name:'Code Agent',tools:['fs_read','fs_patch','fs_write','run_command','git_status','git_diff']})});
        const again=(await api('/api/agents').then(r=>r.json())).agents||[];
        aid=again.find(a=>(a.name||'')==='Code Agent')?.id||again[0]?.id;
      }
      window._openideCodeAgentId=aid;
    }
    let fullPrompt=prompt;
    if(window._openideFetchContext){
      fullPrompt+='\n\n[git fetch context]\n'+window._openideFetchContext;
      window._openideFetchContext='';
    }
    if(window._openideFingerprint&&window._openideFingerprint.ok){
      const fp=window._openideFingerprint;
      fullPrompt+=`\n\n[workspace] branch=${fp.branch||'?'} head=${(fp.head||'').slice(0,12)} dirty=${fp.dirty_count||0}`;
      fullPrompt+=`\n[cortex] orchestrate under git ${fp.head||'unknown'} · invoke rules/skills/subagents`;
    }
    // Multitask: queue via Cortex then also run primary
    if(window._openideAgentMode==='multitask'&&aid){
      try{
        await api('/api/cortex/queue',{method:'POST',body:JSON.stringify({agent_id:aid,prompt:fullPrompt.slice(0,2000),session_id:currentSession||0,skill_pack:window.pendingSkillPack||''})});
      }catch(e){}
    }
    const body={
      prompt:fullPrompt,session_id:currentSession||0,thinking_mode:mode,backend,
      require_approval:true,file_context:true,active_file:openideFile||'',
      resume:!!opts.resume,cursor_run_id:window._openideCursorRunId||''
    };
    if(window.pendingSkillPack){body.skill_pack=window.pendingSkillPack;window.pendingSkillPack='';}
    const r=await fetch(API()+'/api/agents/'+aid+'/run',{
      method:'POST',headers:{'Content-Type':'application/json','X-AirGPT-Token':authToken,'Accept':'text/event-stream'},
      body:JSON.stringify(body)
    });
    let buf='',finalText='';
    const reader=r.body.getReader();const dec=new TextDecoder();
    while(true){
      const {done,value}=await reader.read();if(done)break;
      buf+=dec.decode(value,{stream:true});
      const parts=buf.split('\n\n');buf=parts.pop()||'';
      for(const chunk of parts){
        const line=chunk.split('\n').find(l=>l.startsWith('data:'));
        if(!line)continue;
        let j={};try{j=JSON.parse(line.slice(5).trim())}catch(e){continue}
        if(j.run_id){window._openideCursorRunId=j.run_id;const b=$('openideContinueBtn');if(b)b.style.display=''}
        if(j.type==='write_preview'){renderOpenIDEApproval(j);continue}
        if(j.type==='tool_call'||j.type==='tool'){
          if(thoughtBuf.trim()){openideAppendThought(thoughtBuf,performance.now()-thoughtT0);thoughtBuf='';thoughtT0=performance.now()}
          toolCount++;
          openideAppendTranscript(`<div class="openide-tool-line"><span class="ot-ico">→</span><span>Used tool · <strong>${esc(j.name||'tool')}</strong></span></div>`);
          openideSetStatus(`Used ${toolCount} tool${toolCount===1?'':'s'}…`,true);
        }
        if(j.type==='thinking'){
          const t=(j.text||'').trim();
          if(t){thoughtBuf+=(thoughtBuf?'\n':'')+t;openideSetStatus(t.slice(0,80),true)}
        }
        if(j.type==='status'){
          const t=(j.text||'').trim();
          if(t)openideSetStatus(t.slice(0,100),true);
        }
        if(j.type==='subagent_start'){
          openideAppendTranscript(`<div class="openide-tool-line"><span class="ot-ico">↳</span><span>Subagent · <strong>${esc(j.name||j.id||'child')}</strong> started</span></div>`);
        }
        if(j.type==='subagent_done'){
          openideAppendTranscript(`<div class="openide-tool-line"><span class="ot-ico">✓</span><span>Subagent · ${esc(String(j.id||''))} ${esc(j.status||'done')}</span></div>`);
        }
        if(j.type==='token')finalText+=(j.text||'');
        if(j.type==='done')finalText=j.analysis||finalText;
        if(j.type==='error'){
          $('openideRunningLine')?.remove();
          if(thoughtBuf.trim()){openideAppendThought(thoughtBuf,performance.now()-thoughtT0);thoughtBuf=''}
          openideAppendTranscript(`<div class="openide-msg" style="color:#f87171">${esc(j.text||'Agent error')}</div>`);
          openideSetStatus('Error',false);toast(j.text||'Agent error');
          if(window._openideRuns[0]){window._openideRuns[0].status='error';saveOpenIDERuns()}
          renderOpenIDERunsList();
          return;
        }
      }
    }
    $('openideRunningLine')?.remove();
    if(thoughtBuf.trim()){openideAppendThought(thoughtBuf,performance.now()-thoughtT0);thoughtBuf=''}
    if(finalText.trim())openideAppendTranscript(`<div class="openide-msg">${esc(finalText.trim().slice(0,6000))}</div>`);
    else if(!window._openidePendingWrite)openideAppendTranscript(`<div class="openide-tool-line"><span class="ot-ico">✓</span><span>Done · used ${toolCount} tools · no write preview</span></div>`);
    openideSetStatus(toolCount?`Done · used ${toolCount} tools`:'Done',false);
    if(window._openideRuns[0]){window._openideRuns[0].status='done';saveOpenIDERuns()}
    renderOpenIDERunsList();
    refreshOpenIDEDiffStat();refreshOpenIDEFingerprint();
  }catch(e){
    $('openideRunningLine')?.remove();
    openideAppendTranscript(`<div class="openide-msg" style="color:#f87171">Agent failed</div>`);
    openideSetStatus('Failed',false);
    if(window._openideRuns[0]){window._openideRuns[0].status='failed';saveOpenIDERuns()}
    renderOpenIDERunsList();
  }
}
async function applyOpenIDEPatch(){
  return approveOpenIDEWrite();
}
async function openIDECheckpoint(){
  try{const r=await api('/api/fs/checkpoint',{method:'POST',body:'{}'});toast(r.ok?'Checkpoint saved':r.error)}catch(e){toast('Checkpoint failed')}
}
async function setOpenIDEBackend(v){
  try{await api('/api/openide/backend',{method:'POST',body:JSON.stringify({backend:v})});toast('Backend: '+v)}catch(e){}
}
function openInCursor(){
  const root=($('openideRoot')?.textContent||'').trim();
  if(root&&root!=='No workspace')window.open('cursor://file/'+encodeURIComponent(root));
  else toast('Open a workspace first');
}
async function runOpenIDECmd(solo){
  const cmd=((solo?$('openideCmdSolo'):$('openideCmd'))?.value||'').trim();if(!cmd)return;
  try{
    const r=await api('/api/terminal/exec',{method:'POST',body:JSON.stringify({cmd,session_id:terminalSessionId})});
    const out=(r.stdout||'')+(r.stderr||'')||r.error||'';
    const pre=$('openideTerm');if(pre)pre.textContent=out;
    const soloPre=$('openideTermSolo');if(soloPre)soloPre.textContent=out;
    if(solo&&$('openideCmdSolo'))$('openideCmdSolo').value='';
    else if($('openideCmd'))$('openideCmd').value='';
  }catch(e){toast('Command failed')}
}
