/**
 * AirGPT WASM gate stub — client-side payload inspection before upload.
 * Export: window.AirGPTWasmGate.inspectPayload({text, filename, mime, size})
 */
(function () {
  "use strict";

  const MAX_BYTES = 100 * 1024 * 1024;
  const ALLOWED_MIME_PREFIXES = ["image/", "text/", "application/pdf", "application/json"];
  const CRED_PATTERNS = [
    [/\b(sk-[a-zA-Z0-9]{20,})\b/g, "[REDACTED_OPENAI_KEY]"],
    [/\b(AKIA[0-9A-Z]{16})\b/g, "[REDACTED_AWS_KEY]"],
    [/\b(ghp_[a-zA-Z0-9]{20,})\b/g, "[REDACTED_GH_TOKEN]"],
    [/\b(api[_-]?key\s*[:=]\s*['"]?[a-zA-Z0-9_\-]{12,})/gi, "[REDACTED_API_KEY]"],
    [/\b(password\s*[:=]\s*['"]?[^\s'"]{4,})/gi, "[REDACTED_PASSWORD]"],
    [/\b(Bearer\s+[a-zA-Z0-9._\-]{20,})\b/gi, "[REDACTED_BEARER]"],
  ];

  async function sha256Hex(text) {
    if (!text || !globalThis.crypto?.subtle) return null;
    const enc = new TextEncoder().encode(text);
    const buf = await crypto.subtle.digest("SHA-256", enc);
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }

  function redactText(text) {
    if (!text) return text;
    let out = String(text);
    for (const [re, repl] of CRED_PATTERNS) {
      out = out.replace(re, repl);
    }
    return out;
  }

  function mimeOk(mime) {
    if (!mime) return true;
    const m = String(mime).toLowerCase();
    return ALLOWED_MIME_PREFIXES.some((p) => m.startsWith(p) || m === "application/octet-stream");
  }

  async function inspectPayload({ text = "", filename = "", mime = "", size = 0 } = {}) {
    const reasons = [];
    let ok = true;
    const n = Number(size) || (text ? text.length : 0);

    if (n > MAX_BYTES) {
      ok = false;
      reasons.push("size_exceeded");
    }
    if (mime && !mimeOk(mime)) {
      ok = false;
      reasons.push("mime_blocked");
    }
    if (filename && /\.(exe|bat|cmd|ps1|vbs|scr)$/i.test(filename)) {
      ok = false;
      reasons.push("executable_blocked");
    }

    const redactedText = redactText(text);
    if (text && redactedText !== text) {
      reasons.push("credentials_redacted");
    }

    const hash = await sha256Hex(text || filename || "");
    if (hash) reasons.push("hash:" + hash.slice(0, 16));

    return { ok, reasons, redactedText: redactedText !== text ? redactedText : undefined };
  }

  globalThis.AirGPTWasmGate = { inspectPayload, redactText, sha256Hex };
})();
