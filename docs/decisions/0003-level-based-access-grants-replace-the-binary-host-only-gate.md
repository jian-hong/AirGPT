---
status: proposed
date: 2026-08-07
decision-makers: founder
supersedes: none
relates-to: PRD-001 ledger rows F21-F23; EPIC-D03 jian-hong/AirGPT#26; DR-0002 decision 3
---

# DR-0003 - Level-based access grants replace the binary host-only gate

## Context and Problem Statement

AirGPT ships one access decision, made in one place, on one input: **is the request coming
from this machine?**

```
clipdrop.py:2546 (GET) and clipdrop.py:4026 (POST)
    if _is_host_only_path(path) and not _is_local_host(ip):
        return self._json(403, {"error": "host only"})
```

`_HOST_ONLY_PREFIXES` (`clipdrop.py:786-804`) holds 17 prefixes, and `/api/rag` is one of
them. So a phone that pairs successfully, over a working tunnel, with a valid token, gets
403 on the actual product. The founder's words for the state of the world:

> *"i mean F22 is like now is totlally full access, full control, nexttime we do is level
> based we share what kind of access"*

This gate was shipped deliberately closed (S0 host-only). The founder is now choosing to
open it in a controlled way, which makes this a change to the threat model, not to a
surface - the reason PRD-001 routed F22a to a decision record rather than to an epic.

### What already exists, and why that matters more than it looks

The apparent gap is smaller than the ask suggests, and the parts that exist are weaker
than they appear. Written down here because a design that ignores them will build a second
copy of each, which is the failure mode NETIE.md rule 4 names.

| Thing he asked for | State today | File |
|---|---|---|
| A bar of access levels | **Exists.** `ACL_LEVELS = ("read_only", "read_write", "use_host_ai", "use_own_ai", "limited")`, per-peer menu, POST endpoint, DB column | `hub.py:13`, `hub.py:245`, `index.html:6610,6633` |
| That bar granting anything | **Does not exist.** Its only consumer is a display label | `hub.py:306-314` -> `ai_source` |
| Per-token access level | **Exists and is also unread** - `redeem_join_code` writes `access_level` into token meta | `auth.py:326-330` |
| An authentication code from host, typed by client | **Exists** - 6-char hex join code, 48h TTL | `auth.py:289-314`, `JOIN_CODE_TTL` at `auth.py:254` |
| That code being a real control | **Weak.** 24 bits of entropy, and `redeem_join_code` **never removes the code**, so one code mints unlimited guest tokens for 48 hours | `auth.py:317-336` |
| QR as a credential | **Conditional.** `issue_qr_token` returns `None` when no passcode is set, and `_join_url` returns a bare URL when `needs_auth` is false - in the default no-passcode state the QR carries no token at all | `auth.py:158-168`, `clipdrop.py:1961-1980` |
| Durable link that survives | **Contradicted.** `_qr_join_cache.clear()` fires on every tunnel change; QR tokens are one-time with a 600s TTL | `clipdrop.py:1637,1766`, `QR_TOKEN_TTL` at `auth.py:14` |
| Rate limit on code guessing | **Exists.** 20 failures per 300s per IP, shared with passcode failures, local host exempt | `clipdrop.py:2021-2037` |

The founder ranked the authentication code as the most important control in his message.
It is the one thing on this list that already exists **and** is the one thing on this list
that is measurably too weak for the job he is about to give it. That is the central finding
of this record.

### The founder's answer, verbatim

> *"i mean F22 is like now is totlally full access, full control, nexttime we do is level
> based we share what kind of access, it is like more intregrated with hub, now the access
> and share qr in hub is not working, so if we have set in either some place to contorl
> access, then after sharing, read/ use host/ use api (own compute), then can immediately
> giv ethemt their level of access to each files. also can this level of access to
> sharefrom project folder so ppl can collaborate next time they with the link can visit
> back . Then during first time establish and everytime login through link orscna qr needs
> to use a handshaek, so host cna have multiple requestions, so sequentially or via small
> popups cna minimise or reject, if press poutside region is minimise then as a button or
> unsolved on bottom right, then ya most importantly need give authentication code from
> host then client need to correctly fill in for access"*

One sentence in it is not a design statement but a bug report - *"now the access and share
qr in hub is not working"*. It is carried separately as PRD-001 ledger row **F23** and is
not decided here. A defect in the surface being replaced does not belong inside the
decision that replaces it.

## Considered Options

**Option A - leave the gate closed.** Cheapest and safest. Rejected by the founder, and
correctly: a control that refuses the owner's own phone on his own network is R-0005, a
control refusing legitimate work.

**Option B - make `_is_local_host` accept any authenticated peer.** One line, and it is the
option that will be proposed by whoever reads this next without reading the prefix list.
**Rejected here.** It hands `/api/terminal/` (command execution), `/api/fs/` (workspace
read and write), `/api/agents/` (agent run, a code-execution surface) and `/api/openvault/`
to anyone who scans a QR. The prefixes were enumerated because each one can read or write
the host machine; authenticating the caller does not change what the call does.

**Option C - level-based capability grant with an explicit per-class prefix allowlist,
default closed.** Chosen. Costs a real design and a real test surface, and is the only
option where the answer to "what can this device do" is written down rather than inferred.

## Decision Outcome

Each item below is marked **DECIDED** (resolvable from code, from NETIE.md, or from the
founder's own words) or **FOUNDER OWES** (a choice only he can make, and which blocks
build).

### 1. The gate becomes level-based, and the default stays closed - DECIDED

`_is_local_host` remains sufficient for everything. Remote access is granted only by an
explicit level, and the absence of a level means 403 exactly as today. No prefix becomes
reachable by default, and no future prefix added to `_HOST_ONLY_PREFIXES` becomes reachable
without being named in the map below. **Fail closed on an unknown level, an unknown prefix,
and an expired grant.**

### 2. Which levels are shareable, and what each may reach - DECIDED in part

The founder named three: *"read/ use host/ use api (own compute)"*. These map onto three of
the five existing `ACL_LEVELS`:

| His words | Existing level | Meaning |
|---|---|---|
| read | `read_only` | can read knowledge, cannot spend host compute |
| use host | `use_host_ai` | may spend the host's model budget |
| use api (own compute) | `use_own_ai` | brings its own key, host does not pay |

He did **not** name `read_write` or `limited`.

**DECIDED - the fence, and it is the part of this record that must not be traded away.**
No shareable level, at any tier, ever reaches:

`/api/fs/`, `/api/terminal/`, `/api/workspace`, `/api/git/`, `/api/agents/`,
`/api/cortex/`, `/api/workflows`, `/api/invoke/`, `/api/openide/`, `/api/openvault/`,
`/api/openforge/`, `/api/github`, `/api/engine`, `/api/desktop`, `/api/admin`, `/api/audit`

That is 16 of the 17. A shared link is a reader and a chatter, never an operator. Note the
founder did not ask for any of these - the "full agent" tier appears nowhere in his message,
and this record declines to invent it.

The one prefix that opens is **`/api/rag`**, and only the read paths of it - answer and
source-list. Ingest, build, rebuild, archive and reveal are host-only, because reveal opens
File Explorer on the host and rebuild spends the host's compute for an unbounded time.
Chat (`/api/ai/*`) opens for `use_host_ai` and `use_own_ai`, and stays shut for `read_only`.

**FOUNDER OWES:** (a) confirm the shareable set is exactly those three and that
`read_write` and `limited` stay non-shareable, or name what they mean if they are to be
kept; (b) confirm `/api/rag` read-only is the correct single opening for the first slice.

### 3. Per-file access is the most expensive clause in the message - DECIDED to stage, founder owes the acceptance

> *"then can immediately giv ethemt their level of access to each files"*

**Cost line, stated plainly.** Everything else in this record is a decision about an
existing object - a peer, a token, a level, a prefix. This one requires an object that does
not exist. There is no per-file ACL anywhere in the data model: RAG sources carry no owner
column and no grant table, the space is the smallest unit that has any sharing concept at
all, and the gate is a path-prefix check that never sees a file id. Per-file grants mean a
new table, a new join on every retrieval, and a filter inside the RAG answer path so that a
citation cannot leak a row the reader may not see - which is the manifest-enforced-read
problem from NETIE.md section 3, arriving in AirGPT.

**Recommendation: not in the first slice.** Ship the grant at the level the data model
already has (peer, token, space), prove the fence holds, then decide per-file with evidence.
Shipping per-file first means shipping the hardest half of the manifest problem before the
gate itself has ever been exercised.

**FOUNDER OWES:** accept the staging, or say per-file is required in the first slice - in
which case the appetite is not days, and D01/D02 must close first.

### 4. Durable share links from a project folder - DECIDED in shape, founder owes the lifetime

> *"also can this level of access to sharefrom project folder so ppl can collaborate next
> time they with the link can visit back"*

Two asks. The scope of a share becomes a **project folder**, not only a device; and the
link is **durable** - a returning collaborator uses the same link later.

**DECIDED:** a durable link is a credential with a lifetime, and is therefore a first-class
revocable object, not a URL with a token glued on. It carries: an id, the level, the scope
it grants, who created it, when it expires, and whether it is revoked. It is listed on the
Hub and it can be killed from there. **A link that cannot be revoked from the surface that
created it must not ship.**

**DECIDED - the contradiction, and it is a decision rather than a bug.** Today
`_qr_join_cache.clear()` fires whenever the tunnel changes (`clipdrop.py:1637,1766`), and
QR tokens are one-time with a 600 second TTL. That is correct behaviour for a scan-now
pairing token and it is incompatible with a link someone returns to next week. The
resolution: **the link's identity must not be the tunnel host.** The grant is resolved
server-side from its id, so a changed tunnel URL changes where the link points, not whether
it is valid. Pairing tokens keep their current one-time, short-TTL behaviour. These are two
different objects and must not be merged into one.

**FOUNDER OWES:** the default lifetime of a durable link (proposal: 30 days, renewable from
the Hub, never infinite), and whether revocation is per-link or per-person.

### 5. A handshake on every entry, not only on first pairing - DECIDED

> *"during first time establish and everytime login through link orscna qr needs to use a
> handshaek"*

This is the same control already authorized as **F8a / HOST-DEMO-02** under EPIC-D03
(`/api/establish` or a hardened `/api/probe`, session nonce plus
`X-AirGPT-Security-Version`, chat token bound to the handshake). The founder's answer
extends it from "before `/api/ai/*`" to **every session entry through a link or a QR scan**.
No new mechanism; the existing one is not optional and not once-per-device.

### 6. The host approves requests from a queue, and a minimised request is still pending - DECIDED in shape, founder owes the absent-host rule

> *"so host cna have multiple requestions, so sequentially or via small popups cna minimise
> or reject, if press poutside region is minimise then as a button or unsolved on bottom
> right"*

**DECIDED:** join requests form a queue on the host. Each is individually approvable or
rejectable. Clicking outside minimises rather than dismisses, and minimised requests
collapse to a persistent bottom-right indicator carrying the **unresolved count**.

**DECIDED - the R-0011 clause.** A minimised request must remain pending, must stay counted,
and must expire **visibly**, with the requester told. A pending request that silently
vanishes is a lie about the state of the door - the host believes he refused nobody, the
guest believes he was refused. This is the same failure class as the dead `schedule_hint`
in DR-0002 decision 4, and it is why this clause is written into the record rather than
left to the UI.

**FOUNDER OWES:** what happens when the host is not at the machine - auto-reject after a
timeout (safe, and the guest is told), or hold the request until he returns (convenient,
and a queue of stale requests accumulates). Default should be auto-reject.

### 7. The authentication code is the load-bearing control - and it exists, and it is too weak - DECIDED to harden, founder owes the parameters

> *"most importantly need give authentication code from host then client need to correctly
> fill in for access"*

He is right that this is the most important control, and it is already built. What it is
today, measured:

| Property | Today | Verdict |
|---|---|---|
| Generation | `secrets.token_hex(3).upper()` - 6 hex chars | **24 bits.** Cryptographically random, but short |
| Lifetime | `JOIN_CODE_TTL = 86400 * 2` - 48 hours | Long for a code read aloud once |
| Single use | **No.** `redeem_join_code` never removes the code | **The defect.** One code mints unlimited guest tokens for two days |
| Rate limit | 20 failures per 300s per IP, shared with passcode, local exempt | Real, but per-IP and a tunnel can change IP |
| Binding | None. Any device may redeem any live code | No device or session binding |

A 24-bit multi-use code, valid for 48 hours, redeemable by anyone, over a public tunnel, is
not a control adequate to the levels this record is about to grant. Today that weakness is
partly masked because the gate refuses the guest everything worth having. **Opening the gate
removes the mask.** This is the sentence to re-read before implementing anything else here.

**DECIDED:**
- The code is **single-use** for any level above `read_only`. Redemption removes it.
- Entropy is raised to at least 40 bits for shareable levels (proposal: 8 characters from
  an unambiguous alphabet, no 0/O/1/I/l, so it stays readable aloud).
- TTL for a grant code is minutes, not 48 hours, because the founder's flow is
  host-reads-it-out then client-types-it-now.
- A wrong entry counts toward a **lockout**, not only a throttle, and lockout is per code
  as well as per IP - a code under attack dies rather than surviving 48 hours of guessing.
- The code is the second factor of the handshake in decision 5. It does not replace it.

**FOUNDER OWES:** exact TTL (proposal: 10 minutes), and whether a code is bound to one
device at issue time or to whoever redeems first.

### 8. What this record refuses, and why it is written here rather than left unsaid

**Durable collaboration links into a machine that also serves `/api/terminal/` and
`/api/fs/` is the risky part of this design, and the risk is structural rather than a
matter of care.** The founder asked for a link a collaborator can return to weeks later.
That link lives in a chat history, a phone screenshot, a browser sync, a work laptop
someone left a job with. It points at a laptop that can execute commands and read the
workspace.

The fence in decision 2 is what makes this acceptable, and it holds only for as long as it
is enforced by a test rather than by memory. It is worth stating the specific way this
design fails: **someone adds a prefix to `_HOST_ONLY_PREFIXES` and does not add it to the
class map**, or adds a new capability under a prefix already granted to `read_only`. Both
are silent, and both hand a durable public link something it was never meant to have. The
allowlist must therefore be **positive** (name what each class may reach) and never
subtractive (name what it may not), and a prefix with no class entry must resolve to 403.
That is decision 1's fail-closed clause, restated because this is where it earns its keep.

Two further refusals:

- **No shared level ever reaches an agent-run or terminal surface**, however convenient it
  would be for the collaboration story. If a collaborator needs to run an agent, that is a
  different product decision and needs its own record.
- **This does not make AirGPT a key vault.** If a durable grant is ever backed by a
  capability token that OpenVault issues, custody stays in OpenVault (NETIE.md section 3,
  plane 2). AirGPT holds a grant record, not a key.

## Consequences

**Positive.** The founder's own phone stops being refused, which was R-0005 failing in the
direction nobody notices. The `access_level` bar stops being decorative, so the surface
stops lying (R-0011). What a remote device may do becomes a written table instead of an
emergent property of an IP check.

**Negative and accepted.** The attack surface grows from "the host machine" to "the host
machine plus every live grant". The join code becomes a real credential and inherits the
operational burden of one - rotation, revocation, lockout, and a support story for "I lost
the code". Per-file access (decision 3) is deferred, which means the founder does not get
everything he asked for in the first slice.

**Known gaps this record does not close.** The Hub access control and share QR are reported
broken today (F23); this record assumes they will be fixed before it is built on, and does
not diagnose them. Whether `read_write` and `limited` survive as levels is unanswered.
Per-file grants are unanswered by design. The `/api/rag` read/write split does not exist in
the path structure today - `/api/rag` is one prefix covering answer, ingest, build and
reveal - so decision 2 implies a path-level split that is real work and is not costed here.

## Confirmation

This decision is not accepted until every line below resolves to a file that exists and a
check that can fail. **None of these exist yet** - stated explicitly, because DR-0001 in
this estate already produced the failure of a record naming an enforcer that was never
written.

- `tests/test_access_levels.py` - **does not exist yet.** For each of the 17 entries in
  `_HOST_ONLY_PREFIXES` and each shareable level, assert the granted or refused result.
  The test must enumerate `_HOST_ONLY_PREFIXES` at runtime, so that **adding a prefix
  without a class entry fails the suite** rather than silently defaulting.
- A negative test that a `read_only` grant receives 403 on `/api/terminal/`, `/api/fs/`,
  and `/api/agents/`, asserted on the HTTP response the remote client receives and not on
  an internal helper (R-0001).
- A test that a join code above `read_only` cannot be redeemed twice.
- A test that a revoked durable link stops working immediately, and that a changed tunnel
  URL does **not** invalidate an unrevoked one.
- A test that a minimised join request is still counted as pending and expires visibly.
- R-0005 re-run: after the gate changes, the host itself must lose nothing. The full local
  corpus passes from `127.0.0.1` exactly as before.
- The adversary is not the verifier (NETIE.md rule 3): whoever implements the gate does not
  confirm it.
