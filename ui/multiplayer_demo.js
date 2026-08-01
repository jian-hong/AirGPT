/**
 * YC Multiplayer film surfaces — presence authorship, Hub demo mode,
 * access popover hooks, emergency AI lockdown, OpenVault ship, project share.
 * Loaded after Motion (optional). Lockdown gates real AI providers via the API.
 */
(function (global) {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = global.esc || ((s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c])));
  const api = (...args) => global.api(...args);
  const toast = (m) => (global.toast ? global.toast(m) : console.log(m));

  function accessPopover(ev, opts) {
    const fn = global.__openAccessPopover;
    if (typeof fn === "function") return fn(ev, opts);
    toast("Access control unavailable");
  }

  /* ---------- Presence ---------------------------------------------------- */
  const _presence = { session: 0, by: new Map(), announced: new Set() };

  function presenceColor(name) {
    let h = 0;
    const s = String(name || "?");
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    const hue = h % 360;
    return `hsl(${hue} 55% 42%)`;
  }
  function presenceInitials(name) {
    const parts = String(name || "?").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
  function presenceSpringIn(el) {
    const M = global.Motion;
    if (!M || !M.Spring || document.hidden || (M.prefersReducedMotion && M.prefersReducedMotion())) {
      el.style.transform = "";
      el.style.opacity = "";
      return;
    }
    try {
      el.style.transform = "scale(0.6)";
      el.style.opacity = "0";
      const sp = new M.Spring({
        preset: "snappy",
        from: 0.6,
        onRest: () => { el.style.transform = ""; el.style.opacity = ""; },
        onUpdate: (v) => {
          el.style.transform = `scale(${v})`;
          el.style.opacity = String(Math.max(0, Math.min(1, (v - 0.6) / 0.4)));
        },
      });
      sp.setTarget(1);
    } catch (e) {
      el.style.transform = "";
      el.style.opacity = "";
    }
  }
  function presenceSystemLine(text) {
    const chat = $("chat");
    if (!chat || chat.querySelector(".empty")) return;
    const div = document.createElement("div");
    div.className = "msg-system";
    div.textContent = "— " + text;
    chat.appendChild(div);
    if (typeof global.isChatNearBottom !== "function" || global.isChatNearBottom(160)) {
      if (typeof global.scrollChatBottomNow === "function") global.scrollChatBottomNow();
    }
  }
  function renderPresence(list) {
    const host = $("presenceStack");
    if (!host) return;
    const members = Array.isArray(list) ? list : [];
    const sid = global.currentSession || 0;
    if (_presence.session !== sid) {
      _presence.session = sid;
      _presence.by.clear();
      _presence.announced.clear();
    }
    if (!members.length) {
      host.hidden = true;
      host.innerHTML = "";
      delete host.dataset.sig;
      _presence.by.clear();
      return;
    }
    const next = new Map(members.map((m) => [m.ip, m]));
    const firstPaint = _presence.by.size === 0 && !_presence.announced.size;
    for (const [ip, m] of next) {
      if (!_presence.by.has(ip) && !_presence.announced.has(ip)) {
        _presence.announced.add(ip);
        if (!firstPaint) presenceSystemLine((m.name || ip) + " joined this chat");
      }
    }
    _presence.by = next;
    const shown = members.slice(0, 4);
    const extra = members.length - shown.length;
    const typing = members.filter((m) => m.typing);
    const avs = shown.map((m) => {
      const c = presenceColor(m.name);
      return `<div class="presence-av${m.idle ? " idle" : ""}" data-ip="${esc(m.ip)}" style="background:${c}" title="${esc(m.name)}${m.idle ? " · idle" : ""}">${esc(presenceInitials(m.name))}</div>`;
    }).join("");
    const more = extra > 0
      ? `<div class="presence-more" title="${esc(members.slice(4).map((m) => m.name).join(", "))}">+${extra}</div>`
      : "";
    const dots = typing.length
      ? `<div class="presence-typing" title="${esc(typing.map((m) => m.name).join(", "))} typing"><span></span><span></span><span></span></div>`
      : "";
    const sig = members.map((m) => `${m.ip}:${m.idle ? 1 : 0}:${m.typing ? 1 : 0}`).join("|");
    if (host.dataset.sig !== sig) {
      host.innerHTML = `<div class="presence-avs">${avs}${more}</div>${dots}`;
      host.dataset.sig = sig;
      host.querySelectorAll(".presence-av").forEach((el, i) => setTimeout(() => presenceSpringIn(el), i * 40));
    }
    host.hidden = false;
  }
  let _typingSent = 0;
  let _typingTimer = 0;
  function sendTypingSignal(on) {
    if (!global.currentSession) return;
    const now = Date.now();
    if (on && now - _typingSent < 3000) return;
    _typingSent = on ? now : 0;
    try {
      api("/api/presence/typing", {
        method: "POST",
        body: JSON.stringify({ session_id: global.currentSession, typing: !!on }),
      }).catch(() => {});
    } catch (e) { /* ignore */ }
  }
  function bindPresenceTyping() {
    const el = $("input");
    if (!el || el.dataset.presenceBound) return;
    el.dataset.presenceBound = "1";
    el.addEventListener("input", () => {
      if (!el.value.trim()) return;
      sendTypingSignal(true);
      clearTimeout(_typingTimer);
      _typingTimer = setTimeout(() => sendTypingSignal(false), 4000);
    });
  }

  /* ---------- Edit access (delegates to index.html five-row popover) ------ */
  function closeAccessPopover() {
    document.querySelectorAll(".access-pop").forEach((x) => x.remove());
  }
  function openAccessPopover(ev, opts) {
    return accessPopover(ev, opts);
  }
  function decodeAcl(level) {
    const l = level || "read_only";
    if (l === "use_host_ai") return { ai: "host", canEdit: true };
    if (l === "use_own_ai") return { ai: "own", canEdit: true };
    if (l === "read_write") return { ai: "none", canEdit: true };
    if (l === "limited") return { ai: "none", canEdit: false, limited: true };
    return { ai: "none", canEdit: false };
  }
  function encodeAcl({ ai, canEdit }) {
    if (ai === "host") return canEdit ? "use_host_ai" : "read_only";
    if (ai === "own") return canEdit ? "use_own_ai" : "read_only";
    return canEdit ? "read_write" : "read_only";
  }

  /* ---------- Emergency AI lockdown (Act 4) -------------------------------- */
  let _lockdownTimer = 0;
  let _lockdownWasOn = false;
  function setComposerLockdown(on) {
    const el = $("input");
    const send = document.querySelector(".composer .send");
    if (el) {
      // Disable but NEVER clear — typed draft must survive cut-off + clear.
      el.disabled = !!on;
      el.setAttribute("aria-disabled", on ? "true" : "false");
      if (on) el.blur();
    }
    if (send) send.disabled = !!on;
    document.body.classList.toggle("composer-ai-locked", !!on);
  }
  function applyLockdownUi(ld) {
    const on = !!(ld && ld.on);
    document.body.classList.toggle("ai-lockdown", on);
    setComposerLockdown(on);
    let bar = $("aiLockdownBar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "aiLockdownBar";
      bar.className = "ai-lockdown-bar";
      document.body.appendChild(bar);
    }
    if (!on) {
      bar.hidden = true;
      bar.textContent = "";
      clearInterval(_lockdownTimer);
      if (_lockdownWasOn) toast("AI restored");
      _lockdownWasOn = false;
      return;
    }
    _lockdownWasOn = true;
    const started = Number(ld.started_at || Date.now() / 1000);
    const frozen = Number(
      (global.info && (global.info.online_sessions || global.info.session_count)) ||
      (global._hubOnlineCount) ||
      0
    );
    const tick = () => {
      const sec = Math.max(0, Math.floor(Date.now() / 1000 - started));
      const mm = String(Math.floor(sec / 60)).padStart(2, "0");
      const ss = String(sec % 60).padStart(2, "0");
      const isHost = typeof global.isLocalHost === "function" ? global.isLocalHost() : true;
      bar.hidden = false;
      const frozenLabel = frozen > 0 ? `${frozen} sessions frozen` : "sessions frozen";
      bar.innerHTML = isHost
        ? `AI disabled · ${frozenLabel} · ${mm}:${ss} <button type="button" class="btn" id="lockdownClearBtn">Clear</button>`
        : `Host disabled AI. Your work is saved.`;
      const btn = $("lockdownClearBtn");
      if (btn) btn.onclick = () => setLockdown(false);
    };
    tick();
    clearInterval(_lockdownTimer);
    _lockdownTimer = setInterval(tick, 1000);
    // Stillness window for film
    const M = global.Motion;
    if (M && M.cancelAll) {
      try { M.cancelAll(); } catch (e) { /* ignore */ }
    }
  }
  async function setLockdown(on) {
    try {
      const r = await api("/api/hub/lockdown", {
        method: "POST",
        body: JSON.stringify({ on: !!on, reason: on ? "host cut-off" : "cleared" }),
      }).then((x) => x.json());
      if (global.info) global.info.ai_lockdown = r;
      applyLockdownUi(r);
      if (typeof global.renderHubPage === "function" && global.sideView === "hub") global.renderHubPage();
      toast(on ? "AI cut off for everyone" : "AI restored");
    } catch (e) {
      toast("Lockdown failed");
    }
  }

  /* ---------- Hub demo mode + drawer -------------------------------------- */
  let _hubDemo = localStorage.getItem("airgpt_hub_demo") === "1";
  let _hubDrawerIp = "";

  function hubStateClass(p) {
    if ((p.access_level || "") === "limited") return "state-limited";
    if (!p.online) return "state-offline";
    const age = Date.now() / 1000 - Number(p.last_seen || 0);
    if (age > 300) return "state-idle"; // >5 min — film legend
    return "state-live";
  }

  function hubNodeHtml(node, opts) {
    const hubIconSvg = global.hubIconSvg || (() => "🖥");
    const hubAccessLabel = global.hubAccessLabel || ((l) => l);
    const dull = !!(node.dull && !node.online);
    const st = hubStateClass(node);
    const check = node.logged_in || node.role === "host" ? "✓" : "";
    const ip = node.ip || "";
    const menu = opts && opts.showMenu
      ? `<button type="button" class="hub-node-menu" title="Edit access" onclick="event.stopPropagation();window.MP.openPeerAccess(event,'${esc(ip)}','${esc(node.access_level || "read_only")}')">⋯</button>`
      : "";
    const click = opts && opts.clickable
      ? `onclick="window.MP.openPeerDrawer('${esc(ip)}')"`
      : "";
    return `<div class="hub-node ${node.role === "host" ? "host" : ""} ${dull ? "dull" : ""} ${st}" ${click} data-ip="${esc(ip)}">
      <div class="hub-node-hdr"><span class="hub-node-label">${esc(node.label || node.role || "")}</span>${check ? `<span class="hub-node-check" title="Logged in">${check}</span>` : ""}${menu}</div>
      <div class="hub-node-icon">${hubIconSvg(node.icon)}</div>
      <p class="hub-node-name">${esc(node.username || node.name || "—")}</p>
      <div class="hub-node-meta">IP: ${esc(ip || "—")}<br>${hubAccessLabel(node.access_level)}</div>
    </div>`;
  }

  function openPeerAccess(ev, ip, level) {
    accessPopover(ev, {
      title: "Access",
      level: level || "read_only",
      onPick: async (v) => {
        try {
          await api("/api/hub/peers/" + encodeURIComponent(ip) + "/acl", {
            method: "POST",
            body: JSON.stringify({ access_level: v }),
          });
          toast("Access: " + (global.hubAccessLabel ? global.hubAccessLabel(v) : v));
          if (typeof global.renderHubPage === "function") global.renderHubPage();
        } catch (e) {
          toast("Access change failed");
        }
      },
      extras: [
        {
          label: "Rename…",
          onClick: async () => {
            const n = prompt("Display name");
            if (!n) return;
            try {
              await api("/api/hub/peers/" + encodeURIComponent(ip) + "/rename", {
                method: "POST",
                body: JSON.stringify({ display_name: n }),
              });
              if (typeof global.renderHubPage === "function") global.renderHubPage();
            } catch (e) {
              toast("Rename failed");
            }
          },
        },
        {
          label: "Disconnect",
          onClick: async () => {
            try {
              await api("/api/hub/peers/" + encodeURIComponent(ip) + "/kick", {
                method: "POST",
                body: "{}",
              });
              toast("Disconnected");
              if (typeof global.renderHubPage === "function") global.renderHubPage();
            } catch (e) {
              toast("Kick failed");
            }
          },
        },
      ],
    });
  }

  async function openPeerDrawer(ip) {
    _hubDrawerIp = ip;
    let act = {};
    try {
      act = await api("/api/hub/peers/" + encodeURIComponent(ip) + "/activity").then((r) => r.json());
    } catch (e) {
      toast("Activity unavailable");
      return;
    }
    let drawer = $("hubPeerDrawer");
    if (!drawer) {
      drawer = document.createElement("aside");
      drawer.id = "hubPeerDrawer";
      drawer.className = "hub-peer-drawer";
      document.body.appendChild(drawer);
    }
    const peer = act.peer || {};
    const ai = act.ai_source || {};
    const prompts = (act.prompts || []).map((p) =>
      `<button type="button" class="hub-prompt-row" onclick="window.MP.viewChatMsg(${p.session_id||0},${p.id})">
        <span>${esc((p.text || "").slice(0, 90))}</span>
        <small>View chat →</small>
      </button>`
    ).join("") || `<p class="hint">No prompts yet</p>`;
    drawer.innerHTML = `
      <div class="hub-drawer-hdr">
        <h3>${esc(peer.username || peer.name || ip)}</h3>
        <button type="button" class="btn" data-hub-drawer-close>Close</button>
      </div>
      <p class="hint">${esc(peer.ip || ip)} · ${esc(peer.join_method || "")} · ${esc(global.hubAccessLabel ? global.hubAccessLabel(peer.access_level) : peer.access_level || "")}</p>
      <div class="hub-drawer-card hub-drawer-ai">
        <div class="hub-drawer-k">AI SOURCE</div>
        <div class="hub-drawer-v hub-drawer-ai-label">${esc(ai.label || "—")}</div>
      </div>
      <div class="hub-drawer-card">
        <div class="hub-drawer-k">Tokens today / week</div>
        <div class="hub-drawer-v">${act.tokens_today || 0} / ${act.tokens_week || 0}</div>
        <div class="hint">Cost $${Number(act.cost || 0).toFixed(4)}</div>
        ${(() => {
          const models = act.by_model || [];
          const total = models.reduce((s, m) => s + Number(m.tokens || 0), 0) || 1;
          return models.length
            ? `<div class="hub-token-stack">${models.map((m) => {
                const pct = Math.max(4, Math.round(100 * Number(m.tokens || 0) / total));
                return `<div class="hub-token-seg" style="width:${pct}%" title="${esc(m.model||'')}: ${m.tokens||0}"></div>`;
              }).join("")}</div>`
            : "";
        })()}
      </div>
      <button type="button" class="btn" style="margin-top:12px" data-hub-edit-access>Edit access</button>
      <h4 style="margin:14px 0 8px;font-size:12px;color:var(--muted)">Recent prompts</h4>
      <div class="hub-prompt-list">${prompts}</div>
    `;
    const closeBtn = drawer.querySelector("[data-hub-drawer-close]");
    if (closeBtn) closeBtn.onclick = (ev) => { ev.preventDefault(); ev.stopPropagation(); closePeerDrawer(); };
    const editBtn = drawer.querySelector("[data-hub-edit-access]");
    if (editBtn) editBtn.onclick = (ev) => openPeerAccess(ev, ip, peer.access_level || "read_only");
    drawer.classList.add("open");
    // Fail-visible: rest state is open; spring animates from offset and clears onRest.
    drawer.style.opacity = "";
    drawer.style.transform = "";
    const M = global.Motion;
    if (M && M.Spring && !document.hidden && !(M.prefersReducedMotion && M.prefersReducedMotion())) {
      try {
        drawer.style.transform = "translateX(100%)";
        const rest = () => { drawer.style.transform = ""; drawer.style.opacity = ""; };
        const sp = new M.Spring({
          preset: "sheet",
          from: 100,
          onRest: rest,
          onUpdate: (v) => {
            drawer.style.transform = `translateX(${v}%)`;
          },
        });
        sp.setTarget(0);
        if (M.draggable) {
          try {
            M.draggable(drawer, {
              axis: "x",
              onRelease: (vel) => {
                if (vel > 0.4 || (parseFloat(drawer.style.transform) || 0) > 40) closePeerDrawer();
                else if (sp) sp.setTarget(0);
              },
            });
          } catch (e) { /* ignore */ }
        }
      } catch (e) { /* ignore */ }
    }
  }
  function closePeerDrawer() {
    const drawer = $("hubPeerDrawer");
    if (!drawer) return;
    // Inline transform from the open spring overrides CSS .hub-peer-drawer
    // { transform: translateX(100%) } — so removing .open alone left the panel stuck.
    if (drawer.dataset.closing === "1") return;
    drawer.dataset.closing = "1";
    const finish = () => {
      drawer.classList.remove("open");
      drawer.style.transform = "";
      drawer.style.opacity = "";
      delete drawer.dataset.closing;
      _hubDrawerIp = "";
    };
    const M = global.Motion;
    if (M && M.Spring && !document.hidden && !(M.prefersReducedMotion && M.prefersReducedMotion())) {
      try {
        const fromMatch = /translateX\(([-\d.]+)%\)/.exec(drawer.style.transform || "");
        const from = fromMatch ? parseFloat(fromMatch[1]) : 0;
        const sp = new M.Spring({
          preset: "sheet",
          from,
          onRest: finish,
          onUpdate: (v) => {
            drawer.style.transform = `translateX(${v}%)`;
          },
        });
        sp.setTarget(100);
        setTimeout(finish, 500);
        return;
      } catch (e) { /* fall through */ }
    }
    finish();
  }
  function viewChatMsg(sessionId, msgId) {
    closePeerDrawer();
    if (sessionId && typeof global.openSession === "function") global.openSession(sessionId);
    setTimeout(() => {
      if (typeof global.openItem === "function") global.openItem(msgId);
      const el = document.getElementById("msg-" + msgId);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("msg-flash");
        setTimeout(() => el.classList.remove("msg-flash"), 1600);
      }
      try { location.hash = "msg-" + msgId; } catch (e) { /* ignore */ }
    }, 450);
  }

  function enhanceRenderHubPage(d) {
    const host = d.host || {};
    // Never list the host machine again as a Guest / second Host card.
    const hostIp = String(host.ip || "");
    const allPeers = (d.peers || []).filter((p) => {
      const role = String(p.role || "");
      const ip = String(p.ip || "");
      if (role === "host") return false;
      if (hostIp && ip === hostIp) return false;
      if (ip === "127.0.0.1" || ip === "::1") return false;
      return true;
    });
    const ld = (global.info && global.info.ai_lockdown) || {};
    const lockdownOn = !!ld.on;
    const demo = _hubDemo;
    global._hubOnlineCount = d.online_count || 0;
    let graphHtml = "";
    if (demo) {
      const nodes = [host, ...allPeers];
      const cards = nodes.map((p, i) =>
        `<div class="hub-demo-cell" style="animation-delay:${i * 40}ms">${hubNodeHtml(p, { showMenu: p.role !== "host", clickable: true })}</div>`
      ).join("");
      graphHtml = `<div class="hub-demo-grid">${cards || '<p class="hint">No peers</p>'}</div>`;
    } else {
      const activePeers = allPeers.filter((p) => p.online).slice(0, 4);
      const slots = ["tl", "tr", "bl", "br"];
      const peerHtml = activePeers.map((p, i) =>
        `<div class="hub-peer-pos ${slots[i % 4]}">${hubNodeHtml(p, { showMenu: true, clickable: true })}</div>`
      ).join("");
      graphHtml = `<div class="hub-graph">
        <div class="hub-host">${hubNodeHtml(host)}</div>
        ${peerHtml || '<p class="hint" style="text-align:center;margin-top:40px">No active guests — share a team code or QR.</p>'}
      </div>`;
    }
    const idlePeers = allPeers.filter((p) => !p.online);
    const events = (d.events || []).slice(0, 8).map((e) =>
      `<div class="hint" style="padding:2px 0">${esc(e.event_type || "")} · ${esc(e.ip || "")} · ${esc((e.detail || "").slice(0, 60))}</div>`
    ).join("") || "";
    const shareLevel = $("hubShareLevelBtn")?.dataset.level || "read_only";
    return `<div class="hub-page chat-page-enter${lockdownOn ? " lockdown-wash" : ""}">
      <div class="hub-title-row">
        <div>
          <h2 class="hub-title">Coherent Access Hub</h2>
          <p class="cortex-tag">Host manages who joins, what they can do, and how they use AI.</p>
        </div>
        <label class="hub-demo-toggle"><input type="checkbox" id="hubDemoToggle"${demo ? " checked" : ""}/> Demo mode</label>
      </div>
      <div class="hub-share-row">
        <label class="hint">Share access:</label>
        <button type="button" class="btn" id="hubShareLevelBtn" data-level="${esc(shareLevel)}" onclick="window.MP.pickShareLevel(event)">${esc(global.hubAccessLabel ? global.hubAccessLabel(shareLevel) : shareLevel)} ▾</button>
        <button type="button" class="btn primary" onclick="hubCreateJoinCode()">Team code</button>
        <button type="button" class="btn" onclick="shareSession(currentSession||0,'view')">QR View</button>
        <span class="hint" id="hubJoinCodeHint">${d.join_code ? `Code: <strong style="color:#fff">${esc(d.join_code)}</strong>` : ""}</span>
      </div>
      <div class="hub-actions">
        <button type="button" class="btn danger-wide" id="hubLockdownBtn" onclick="window.MP.confirmLockdown()">${lockdownOn ? "AI cut-off active" : "Cut all AI · everyone"}</button>
      </div>
      ${graphHtml}
      <p class="hint">${d.online_count || 0} online · ${idlePeers.length} inactive · ${d.total_peers || 0} total peers · green live · amber idle · grey off · red limited</p>
      ${idlePeers.length && !demo ? `<div class="cortex-card" style="margin-top:14px"><h3>Inactive · full list</h3><div class="sc-connect-devs">${idlePeers.map((p) => (global.hubMiniRowHtml ? global.hubMiniRowHtml(p, { canKick: p.role !== "host" }) : "")).join("")}</div></div>` : ""}
      ${d.business && events ? `<div class="cortex-card" style="margin-top:12px"><h3>Recent activity</h3>${events}</div>` : ""}
    </div>`;
  }

  function afterHubRender() {
    const tog = $("hubDemoToggle");
    if (tog) {
      tog.onchange = () => {
        _hubDemo = !!tog.checked;
        localStorage.setItem("airgpt_hub_demo", _hubDemo ? "1" : "0");
        if (typeof global.renderHubPage === "function") global.renderHubPage();
      };
    }
    // Fail-visible stagger: rest state is visible; spring from offset when foreground.
    const M = global.Motion;
    document.querySelectorAll(".hub-node").forEach((el, i) => {
      el.style.opacity = "";
      el.style.transform = "";
      if (!M || !M.Spring || document.hidden) return;
      try {
        el.style.transform = "scale(0.92)";
        setTimeout(() => {
          const rest = () => { el.style.transform = ""; el.style.opacity = ""; };
          const sp = new M.Spring({
            preset: "snappy",
            from: 0.92,
            onRest: rest,
            onUpdate: (v) => {
              el.style.transform = `scale(${v})`;
            },
          });
          sp.setTarget(1);
        }, i * 40);
      } catch (e) { /* ignore */ }
    });
  }

  function pickShareLevel(ev) {
    const btn = $("hubShareLevelBtn");
    accessPopover(ev, {
      title: "Share access",
      level: btn?.dataset.level || "read_only",
      onPick: (v) => {
        if (btn) {
          btn.dataset.level = v;
          btn.textContent = (global.hubAccessLabel ? global.hubAccessLabel(v) : v) + " ▾";
        }
      },
    });
  }
  function confirmLockdown() {
    const ld = (global.info && global.info.ai_lockdown) || {};
    if (ld.on) {
      setLockdown(false);
      return;
    }
    if (!confirm("Cut all AI for everyone?\n\nPeers keep their typed text. In-flight answers are saved. AI stays off until you Clear.")) return;
    setLockdown(true);
  }

  /* ---------- Project share + OpenVault ship ------------------------------ */
  async function shareProject(catKey, level) {
    level = level || "read_only";
    try {
      const r = await api("/api/projects/" + encodeURIComponent(catKey) + "/share", {
        method: "POST",
        body: JSON.stringify({ acl: level, access_level: level }),
      }).then((x) => x.json());
      if (!r.ok) {
        // Fallback: session share if project route unavailable
        const sessions = (global.cachedCategories || []).find((c) => (c.key || c.name) === catKey)?.sessions || [];
        const sid = sessions[0]?.id || global.currentSession || 0;
        if (!sid) {
          toast(r.error || "Share failed");
          return;
        }
        const acl = level === "read_only" || level === "limited" ? "view" : "post";
        const rs = await api("/api/sessions/" + sid + "/share", {
          method: "POST",
          body: JSON.stringify({ acl, access_level: level }),
        }).then((x) => x.json());
        if (!rs.ok) {
          toast(rs.error || "Share failed");
          return;
        }
        return showProjectShareModal(catKey, level, rs.share_url || "");
      }
      return showProjectShareModal(catKey, level, r.share_url || "");
    } catch (e) {
      toast("Share failed");
    }
  }
  function showProjectShareModal(catKey, level, url) {
    if (typeof global.netieOpenModal !== "function") {
      toast(url || "Share ready");
      return;
    }
    global.__projectShareUrl = url;
    global.__projectShareKey = catKey;
    global.__projectShareLevel = level;
    global.netieOpenModal("Share this project", `
      <p class="hint" style="margin:0 0 10px">Default is <strong>Manual</strong> — no AI. Raise access on purpose.</p>
      <button type="button" class="btn" id="projShareAclBtn" data-level="${esc(level)}">${esc(global.hubAccessLabel ? global.hubAccessLabel(level) : level)} ▾</button>
      <div class="share-qr-actions" style="max-width:240px;margin:12px auto 0">
        <img class="qr-img" id="qrProjectShareModal" alt="Share QR"/>
        <button type="button" class="qr-share-btn" onclick="copyText(window.__projectShareUrl||'')">Copy link</button>
      </div>
      <p class="hint" style="margin-top:10px;word-break:break-all">${esc(url)}</p>`);
    setTimeout(() => {
      const el = $("qrProjectShareModal");
      if (el && typeof global.setQR === "function") global.setQR(el, url);
      const btn = $("projShareAclBtn");
      if (btn) {
        btn.onclick = (ev) => accessPopover(ev, {
          title: "Project access",
          level: btn.dataset.level || "read_only",
          onPick: (v) => {
            btn.dataset.level = v;
            btn.textContent = (global.hubAccessLabel ? global.hubAccessLabel(v) : v) + " ▾";
            shareProject(catKey, v);
          },
        });
      }
    }, 30);
  }

  async function shipProjectFlow(projectName) {
    const name = projectName || "vitron-forward";
    if (typeof global.netieOpenModal !== "function") {
      toast("Ship UI unavailable");
      return;
    }
    global.netieOpenModal("Ship to OpenVault", `
      <div class="ov-ship-steps" id="ovShipSteps">
        <ol class="ov-stepper" id="ovStepper">
          <li data-step="sync">Sync</li>
          <li data-step="detect">Detect</li>
          <li data-step="build">Build</li>
          <li data-step="ship">Ship</li>
        </ol>
        <pre id="ovShipLog" class="ov-ship-log">Ready.</pre>
        <div class="hub-actions">
          <button type="button" class="btn primary" id="ovShipGo">Run pipeline</button>
          <button type="button" class="btn" id="ovShipShare" hidden>Share</button>
        </div>
        <div id="ovShipResult" hidden></div>
      </div>`);
    const log = (line) => {
      const el = $("ovShipLog");
      if (el) el.textContent += "\n" + line;
    };
    const mark = (step) => {
      document.querySelectorAll("#ovStepper li").forEach((li) => {
        li.classList.toggle("on", li.dataset.step === step);
        if (li.dataset.step === step) li.classList.add("done");
      });
    };
    $("ovShipGo").onclick = async () => {
      try {
        mark("sync");
        log("Syncing…");
        const sync = await api("/api/openvault/sync", {
          method: "POST",
          body: JSON.stringify({ project: name }),
        }).then((r) => r.json());
        (sync.lines || []).forEach(log);
        if (sync.files_copied != null) log(`Files copied: ${sync.files_copied}`);
        if (!sync.ok) { log("Sync failed"); return; }
        mark("detect");
        log("Detecting…");
        const det = await api("/api/openvault/detect?project=" + encodeURIComponent(name)).then((r) => r.json());
        if (!det.ok) { log(det.error || "Detect failed"); return; }
        log(`Framework: ${det.framework || "—"}`);
        if (det.evidence) log(`Evidence: ${det.evidence}`);
        mark("build");
        log("Building…");
        const bld = await api("/api/openvault/build", {
          method: "POST",
          body: JSON.stringify({ project: name }),
        }).then((r) => r.json());
        (bld.lines || []).forEach(log);
        if (bld.stdout) log(String(bld.stdout).slice(0, 2000));
        mark("ship");
        log("Shipping…");
        const ship = await api("/api/openvault/ship", {
          method: "POST",
          body: JSON.stringify({ project: name }),
        }).then((r) => r.json());
        const box = $("ovShipResult");
        if (box) {
          box.hidden = false;
          const sim = !!ship.simulated;
          const label = sim
            ? "<strong>Simulated target</strong>"
            : esc(ship.label || "");
          const fw = (ship.detect && ship.detect.framework) || det.framework || "";
          const evidence = (ship.detect && ship.detect.evidence) || det.evidence || "";
          // ec2_hint is fake layout reference — never render as deploy target.
          box.innerHTML = `<p><a href="${esc(ship.url || "#")}" target="_blank" rel="noopener">${esc(ship.url || "")}</a></p>
            <p class="hint">${label}</p>
            ${fw ? `<p class="hint"><strong>${esc(fw)}</strong>${evidence ? " · " + esc(evidence) : ""}</p>` : ""}`;
        }
        const sh = $("ovShipShare");
        if (sh) {
          sh.hidden = false;
          sh.onclick = (ev) => accessPopover(ev, {
            title: "Share shipped app",
            level: "read_only",
            onPick: (v) => shareProject(name, v),
          });
        }
      } catch (e) {
        log("Pipeline error: " + e);
      }
    };
  }

  /* ---------- Hooks for index.html ---------------------------------------- */
  function onWaitPayload(d) {
    try { renderPresence(d.presence); } catch (e) { /* ignore */ }
    if (d.ai_lockdown) {
      if (global.info) global.info.ai_lockdown = d.ai_lockdown;
      applyLockdownUi(d.ai_lockdown);
    }
  }
  function onInfoPayload(d) {
    if (d && d.ai_lockdown) applyLockdownUi(d.ai_lockdown);
  }
  function authorChipHtml(m, me, isAi) {
    const dn = (m.device_name || "").trim();
    if (isAi || me || !dn) return "";
    return `<div class="msg-author"><span class="msg-author-dot" style="background:${presenceColor(dn)}"></span>${esc(dn)}</div>`;
  }
  function ensurePresenceHost() {
    if ($("presenceStack")) return;
    const bar = document.querySelector(".chat-titlebar-main") || document.querySelector(".chat-titlebar");
    if (!bar) return;
    const el = document.createElement("div");
    el.className = "presence-stack";
    el.id = "presenceStack";
    el.hidden = true;
    el.setAttribute("aria-label", "People in this chat");
    bar.appendChild(el);
  }
  function boot() {
    ensurePresenceHost();
    bindPresenceTyping();
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && $("hubPeerDrawer")?.classList.contains("open")) {
        closePeerDrawer();
      }
    });
    // Hash deep-link #msg-N
    const m = /^#msg-(\d+)$/.exec(location.hash || "");
    if (m) setTimeout(() => viewChatMsg(0, +m[1]), 800);
  }

  global.MP = {
    renderPresence,
    onWaitPayload,
    onInfoPayload,
    authorChipHtml,
    presenceColor,
    openAccessPopover,
    openPeerAccess,
    openPeerDrawer,
    closePeerDrawer,
    viewChatMsg,
    enhanceRenderHubPage,
    afterHubRender,
    pickShareLevel,
    confirmLockdown,
    setLockdown,
    shareProject,
    shipProjectFlow,
    hubNodeHtml,
    decodeAcl,
    encodeAcl,
    boot,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    setTimeout(boot, 0);
  }
})(typeof window !== "undefined" ? window : globalThis);
