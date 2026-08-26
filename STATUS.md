# STATUS

**Hard cap: 60 lines.** Older narrative moves to CHANGELOG.md.

## Now

0. **D07 #36 leftover** - retained F13 A/B: `oracle_cross_latest.json` holds
   `sira_max` AND `hybrid_max` on the same generated asks (frtr_0001 n=7 smoke).
   Gate `test_oracle_cross_variants_gate.py`. `frtr_cross_latest.json` now has
   both variants too (6 gold Qs). n=320 two-variant still owed for #13/#36 close.
1. **Verify-close R-0003 (2026-08-26)** - closed **#3**, **#33**, **#34**. **#31**
   and **#32** already CLOSED. **#42** stays OPEN until live host handshake.
2. **F13a MET 400/400** (clean). F13b engine 320/320 is SQL-lane-only, not the
   sira vs hybrid A/B. `malformed_ask_rate` 0.0 on those artifacts.
3. **#21 SQL lane default-on** - `default_space_sql_gate.py` 7/7.
4. **D02 ops HTTP** - `test_ops_http_gate.py`. UI callers 0.
5. Orphan parents: D07 #36 (#13 #21), D06 #37 (#17-19 #35), D08 #38 (#14 #15 #20 #25).

## Next

0. **#13/#36 not closeable yet** - F13 A/B smoke is retained (n=7). Still need
   n>=320 two-variant on primary50, F13b floors (0.99 / 0.95 / 0.90), and a
   different-run close. Do not quote 720/720 as the sira vs hybrid number.
1. **READY for different-run close:** **#14** reveal, **#15** SSE chain, **#20**
   Docs originals, **#25** Settings 3/4, **#21** SQL lane.
2. **#42 HOST-DEMO-02** - loopback handshake proven; live host demo still owed.
3. **P13 multilingual** - `multilingual_gate.py` **7/25, deliberately red** (R-0002).
4. Constructor sidecar landed (#48). OpenVault nvidia still separate.

## WIP

In flight: D07 #36, D03 #26. Queued parents: D06 #37, D08 #38, D04 #22, D05.
Never close an epic to free a slot - move it to queued.

## Later

- P1 50GB / P2 Meta SIRA / P3 charts / P4 vault-first / P5 Outerbase-Grafana / P6 2GB / P7 NVIDIA default after OV probe

## Demo open

- `tests/RAG/DEMO_RAG.md`, `results/ontology_space_8.json`. Suite 399 pass / 3 fail (Playwright, empty base URL, unrelated).
