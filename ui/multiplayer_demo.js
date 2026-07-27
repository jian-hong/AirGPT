/**
 * YC Multiplayer film surfaces — presence authorship, Hub demo mode,
 * Edit access popover, mock AI lockdown, OpenVault one-shot, project share.
 * Loaded after Motion (optional). Does not gate real AI providers.
 */
(function (global) {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = global.esc || ((s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c])));
  const api = (...args) => global.api(...args);
  const toast = (m) => (global.toast ? global.toast(m) : console.log(m));

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

  /* ---------- Edit access (3 radios + can edit) --------------------------- */
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
  function closeAccessPopover() {
    document.querySelectorAll(".access-pop").forEach((x) => x.remove());
  }
  function openAccessPopover(ev, opts) {
    ev && ev.stopPropagation && ev.stopPropagation();
    closeAccessPopover();
    const o = opts || {};
    const cur = decodeAcl(o.level || "read_only");
    const pop = document.createElement("div");
    pop.className = "access-pop";
    const rows = [
      { ai: "none", label: "Read only", hint: "can watch, cannot type" },
      { ai: "host", label: "Use Host AI", hint: "spends your tokens" },
      { ai: "own", label: "Use Own AI", hint: "brings their own key" },
    ];
    pop.innerHTML =
      `<div class="access-pop-title">${esc(o.title || "Edit access")}</div>` +
      rows.map((r) =>
        `<button type="button" class="access-row${cur.ai === r.ai ? " on" : ""}" data-ai="${r.ai}">
           <span class="access-radio" aria-hidden="true"></span>
           <span class="access-row-main"><b>${esc(r.label)}</b><small>${esc(r.hint)}</small></span>
         </button>`
      ).join("") +
      `<label class="access-check"><input type="checkbox" id="accessCanEdit"${cur.canEdit ? " checked" : ""}/> Can edit messages</label>` +
      ((o.extras || []).length ? `<div class="access-pop-sep"></div>` : "") +
      (o.extras || []).map((x, i) => `<button type="button" class="access-extra" data-x="${i}">${esc(x.label)}</button>`).join("");
    document.body.appendChild(pop);
    const apply = () => {
      const ai = pop.querySelector(".access-row.on")?.dataset.ai || "none";
      const canEdit = !!pop.querySelector("#accessCanEdit")?.checked;
      const level = encodeAcl({ ai, canEdit });
      closeAccessPopover();
      o.onPick && o.onPick(level);
    };
    pop.querySelectorAll(".access-row").forEach((b) => {
      b.onclick = () => {
        pop.querySelectorAll(".access-row").forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        apply();
      };
    });
    pop.querySelector("#accessCanEdit")?.addEventListener("change", apply);
    pop.querySelectorAll(".access-extra").forEach((b) => {
      b.onclick = () => {
        const x = (o.extras || [])[+b.dataset.x];
        closeAccessPopover();
        x && x.onClick && x.onClick();
      };
    });
    const r = pop.getBoundingClientRect();
    const x = Math.min(Math.max(8, (ev?.clientX || 120) - 12), innerWidth - r.width - 8);
    const y = Math.min(Math.max(8, (ev?.clientY || 120) + 8), innerHeight - r.height - 8);
    pop.style.left = x + "px";
    pop.style.top = y + "px";
    const M = global.Motion;
    if (M && M.Spring && !document.hidden && !(M.prefersReducedMotion && M.prefersReducedMotion())) {
      try {
        pop.style.transform = "translate3d(0,-6px,0)";
        pop.style.opacity = "0";
        const sp = new M.Spring({
          preset: "snappy",
          from: -6,
          onRest: () => { pop.style.transform = ""; pop.style.opacity = ""; },
          onUpdate: (v) => {
            pop.style.transform = `translate3d(0,${v}px,0)`;
            pop.style.opacity = String(Math.max(0, Math.min(1, 1 - Math.abs(v) / 6)));
          },
        });
        sp.setTarget(0);
      } catch (e) { /* ignore */ }
    }
    setTimeout(() => document.addEventListener("click", closeAccessPopover, { once: true }), 0);
    return pop;
  }

  /* ---------- Mock lockdown (film Act 4) ---------------------------------- */
  let _lockdownTimer = 0;
  function applyLockdownUi(ld) {
    const on = !!(ld && ld.on);
    document.body.classList.toggle("ai-lockdown", on);
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
      return;
    }
    const started = Number(ld.started_at || Date.now() / 1000);
    const tick = () => {
      const sec = Math.max(0, Math.floor(Date.now() / 1000 - started));
      const mm = String(Math.floor(sec / 60)).padStart(2, "0");
      const ss = String(sec % 60).padStart(2, "0");
      const isHost = typeof global.isLocalHost === "function" ? global.isLocalHost() : true;
      bar.hidden = false;
      bar.innerHTML = isHost
        ? `AI disabled · sessions frozen · ${mm}:${ss} <button type="button" class="btn" id="lockdownClearBtn">Cleared</button>`
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
        body: JSON.stringify({ on: !!on, reason: on ? "demo cut-off" : "cleared" }),
      }).then((x) => x.json());
      applyLockdownUi(r);
      if (typeof global.renderHubPage === "function" && global.sideView === "hub") global.renderHubPage();
      toast(on ? "AI cut-off (demo)" : "Danger cleared");
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
    if (age > 60) return "state-idle";
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
    openAccessPopover(ev, {
      title: "Edit access",
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
        <button type="button" class="btn" onclick="window.MP.closePeerDrawer()">Close</button>
      </div>
      <p class="hint">${esc(peer.ip || ip)} · ${esc(global.hubAccessLabel ? global.hubAccessLabel(peer.access_level) : peer.access_level || "")}</p>
      <div class="hub-drawer-card">
        <div class="hub-drawer-k">AI source</div>
        <div class="hub-drawer-v">${esc(ai.label || "—")}</div>
      </div>
      <div class="hub-drawer-card">
        <div class="hub-drawer-k">Tokens today / week</div>
        <div class="hub-drawer-v">${act.tokens_today || 0} / ${act.tokens_week || 0}</div>
        <div class="hint">Cost $${Number(act.cost || 0).toFixed(4)}</div>
      </div>
      <h4 style="margin:14px 0 8px;font-size:12px;color:var(--muted)">Recent prompts</h4>
      <div class="hub-prompt-list">${prompts}</div>
      <button type="button" class="btn" style="margin-top:12px" onclick="window.MP.openPeerAccess(event,'${esc(ip)}','${esc(peer.access_level || "read_only")}')">Edit access</button>
    `;
    drawer.classList.add("open");
    const M = global.Motion;
    if (M && M.springTo) {
      try {
        drawer.style.transform = "translateX(100%)";
        M.springTo(drawer, { transform: "translateX(0%)" }, { preset: "sheet" });
      } catch (e) { /* ignore */ }
    }
  }
  function closePeerDrawer() {
    const drawer = $("hubPeerDrawer");
    if (!drawer) return;
    drawer.classList.remove("open");
    _hubDrawerIp = "";
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
    const allPeers = (d.peers || []).slice();
    const ld = (global.info && global.info.ai_lockdown) || {};
    const lockdownOn = !!ld.on;
    const demo = _hubDemo;
    let graphHtml = "";
    if (demo) {
      const cards = allPeers.map((p, i) =>
        `<div class="hub-demo-cell" style="animation-delay:${i * 40}ms">${hubNodeHtml(p, { showMenu: true, clickable: true })}</div>`
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
    // Stagger hub nodes with Motion
    const M = global.Motion;
    document.querySelectorAll(".hub-node").forEach((el, i) => {
      if (!M || !M.Spring || document.hidden) return;
      try {
        el.style.opacity = "0";
        el.style.transform = "scale(0.92)";
        setTimeout(() => {
          const sp = new M.Spring({
            preset: "snappy",
            from: 0.92,
            onRest: () => { el.style.transform = ""; el.style.opacity = ""; },
            onUpdate: (v) => {
              el.style.transform = `scale(${v})`;
              el.style.opacity = String(Math.max(0, Math.min(1, (v - 0.85) / 0.15)));
            },
          });
          sp.setTarget(1);
        }, i * 40);
      } catch (e) { /* ignore */ }
    });
  }

  function pickShareLevel(ev) {
    const btn = $("hubShareLevelBtn");
    openAccessPopover(ev, {
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
    if (!confirm("Cut all AI for everyone? (Demo visual — work is saved.)")) return;
    setLockdown(true);
  }

  /* ---------- Project share + OpenVault ship ------------------------------ */
  async function shareProject(catKey, level) {
    level = level || "read_only";
    const sessions = (global.cachedCategories || []).find((c) => (c.key || c.name) === catKey)?.sessions || [];
    const sid = sessions[0]?.id || global.currentSession || 0;
    if (!sid) {
      toast("Open a chat in this project first");
      return;
    }
    const acl = level === "read_only" || level === "limited" ? "view" : "post";
    try {
      const r = await api("/api/sessions/" + sid + "/share", {
        method: "POST",
        body: JSON.stringify({ acl }),
      }).then((x) => x.json());
      if (!r.ok) {
        toast(r.error || "Share failed");
        return;
      }
      const url = r.share_url || "";
      if (typeof global.netieOpenModal === "function") {
        global.__projectShareUrl = url;
        global.__projectShareLevel = level;
        global.netieOpenModal("Share this project", `
          <p class="hint" style="margin:0 0 10px">Default is <strong>Read only</strong>. Raise access on purpose.</p>
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
            btn.onclick = (ev) => openAccessPopover(ev, {
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
      } else toast("Project share ready");
    } catch (e) {
      toast("Share failed");
    }
  }

  async function shipProjectFlow(projectName) {
    const name = projectName || "vitron-forward";
    if (typeof global.netieOpenModal !== "function") {
      toast("Ship UI unavailable");
      return;
    }
    global.netieOpenModal("Ship to OpenVault", `
      <div class="ov-ship-steps" id="ovShipSteps">
        <p class="hint">One-shot: Sync → Detect → Build → Ship</p>
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
    $("ovShipGo").onclick = async () => {
      try {
        log("Syncing…");
        const sync = await api("/api/openvault/sync", {
          method: "POST",
          body: JSON.stringify({ project: name }),
        }).then((r) => r.json());
        (sync.lines || []).forEach(log);
        if (!sync.ok) { log("Sync failed"); return; }
        log("Detecting…");
        const det = await api("/api/openvault/detect?project=" + encodeURIComponent(name)).then((r) => r.json());
        if (!det.ok) { log(det.error || "Detect failed"); return; }
        log(`Detected: ${det.framework} — ${det.evidence || ""}`);
        log("Building…");
        const bld = await api("/api/openvault/build", {
          method: "POST",
          body: JSON.stringify({ project: name }),
        }).then((r) => r.json());
        (bld.lines || []).forEach(log);
        log("Shipping…");
        const ship = await api("/api/openvault/ship", {
          method: "POST",
          body: JSON.stringify({ project: name }),
        }).then((r) => r.json());
        const box = $("ovShipResult");
        if (box) {
          box.hidden = false;
          box.innerHTML = `<p><a href="${esc(ship.url || "#")}" target="_blank" rel="noopener">${esc(ship.url || "")}</a></p>
            <p class="hint">${ship.simulated ? "<strong>Simulated target</strong>" : esc(ship.label || "")}</p>`;
        }
        const sh = $("ovShipShare");
        if (sh) {
          sh.hidden = false;
          sh.onclick = (ev) => openAccessPopover(ev, {
            title: "Share shipped app",
            level: "read_only",
            onPick: (v) => toast("Shared as " + v),
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
