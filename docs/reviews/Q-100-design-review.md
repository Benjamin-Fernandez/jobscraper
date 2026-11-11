# Q-100 design review (Stage E cross-review, reviewer, 2026-11-11)

Subject: `docs/architecture/q100_ui_design.md` @ b3de745 (DRAFT) with ADR-0009, D-190..D-193, against
`05_workflow.md` §5 ("Design or contracts" and "Build plan") and my audit `docs/reviews/Q-100-ui-audit.md`.
Code was spot-checked on `personal` @ 1987b14. Skills used: engineering:code-review (design mode),
design:design-critique, design:accessibility-review.

**Verdict: REVISE.** 1 BLOCKING (the build-plan merge order), 6 MAJOR, 9 MINOR. The core design holds:
one state vocabulary, a read-only `/api/connections`, a probe off the request path, no secret to the
browser, and the hub under Settings. All fixes are small and stay inside the design doc.

## 1. Hypotheses

**H1 Secrets and paths (ADR-0009): no leak found.** §3.1 sends only booleans (`has_password`), addresses
(D-193), hosts, dates, codes and the model tag. `vault_service`, `unavailable_reason` (contains the URL,
`backends.py:128-137`) and the profile path (contains the Windows user name) are excluded explicitly.
`account_view.message` is fixed copy from `SYNC_TEXTS` (`mailstatus/contracts.py:360+`). The CLI hint
(`accounts add --url … --email …`) prompts for the password itself and puts no secret on the page. MINOR-1
below covers the remaining edges.

**H2 Probe.** The probe is non-blocking and GPU-safe. `/api/tags` lists models and loads none
(`backends.py:120-141`). `snapshot()` returns the cache immediately; a thread does the GET with a 5 s timeout.
It is thread-safe only if the "probe in flight" flag is set inside the same lock as the staleness check.
§3.3 says "behind a lock" and "at most one thread" but doesn't say this; spell it out (MINOR-2).
A fresh backend per probe is cheap: `OllamaBackend.__init__` builds an `httpx.Client` (`backends.py:108-118`).
But that client is never closed, so while Ollama is down a new pool leaks every 15 s (MINOR-3). The real
gap is MAJOR-1 below (`OffBackend`).

**H3 Coupling to `account_view`.** Importing `web/routers/mail.py` into the "pure" `web/connections.py` pulls in
fastapi, the vault and `mailsync`, and depends on a peer function's dict keys (`consent_current`, `message`,
`counts`; `mail.py:119-134`). A peer rename breaks the hub without failing a test in the peer's lane. See MAJOR-2.

**H4 Lane disjointness.** Files per lane, from §8:
- **T0:** `web/src/fixtures/connections.sample.json`, plus Python fixtures (path not named).
- **A:** `web/connections.py`, `web/routers/connections.py`, `web/api.py`, `backends.py`.
- **B:** `connections.js`, `connections_api.js`, `api.js` (an `export` only), `ConnectionsHub.vue`, `ConnectionCard.vue`, `EmployerAccounts.vue`, `ApplySettings.vue`, `tabs/Settings.vue`.
- **C:** `route.js`, `App.vue`, `tabs.js`, `AttentionBanner.vue`, `setup.js`, `SetupChecklist.vue`, `Overview.vue`, `Profile.vue`, `Applications.vue`, `ApplicationDetails.vue`, `JobStatus.vue`.

No file is listed twice, so the lanes are file-disjoint as written. They are not independent, though:
- C imports B's `connections.js` and `connections_api.js`, and B's `Settings.vue` imports C's `route.js`. That is a cycle (BLOCKING-1).
- `style.css` (the chip, banner and bottom-bar tokens) has no owner.
- `ToastHost.vue` (fixed bottom) and `shell.js` (if Settings takes `connections` as a prop) have no owner.
- No lane owns the existing tests that the restructure breaks (MAJOR-5).

Routers are auto-discovered (`web/routers/__init__.py`), so A edits `api.py` only for `model_health`. That is fine.

**H5 Audit coverage.** The P0/P1 findings without a full Wave 1 fix:
- **A1 (P0):** the view and the exact CLI command ship in Wave 1. The repair (G2) is Wave 2 / KA-3, which is acceptable, but the attempt failure text keeps naming `accounts add` until then (`apply/accounts.py:29-31`).
- **A4 (P1):** the "application details" step is dropped whenever `/api/apply/status` 404s (§4.2). It doesn't need to be: `GET /api/applicant` already returns `missing` (`web/routers/applicant.py:134`) (MAJOR-3).
- **A5:** descoped by D-192.
- **A7:** the Inbox half is sent to a peer as R1.
- **A2:** sign-ins (G6) are Wave 2, and `in_use` misses the main path today (MINOR-4).

A3, A6, A9, A10 (Settings), A12, A13 and A14 are covered.

**H6 390 px.** The bottom bar (A14) and the 44 px targets on it and on A13 are right. Gaps:
- The fixed bar covers the Profile sticky save bar (`ApplicationDetails.vue:893-894`, `bottom: 0`) and the toasts (`ToastHost.vue:75-77`) (MAJOR-4).
- No 44 px rule is stated for the other new controls ("How to fix ▾", "Check again", the banner's Fix it/Dismiss, "Later").
- The `<code>` CLI line needs to wrap.
- Four Settings view tabs plus a badge (`Accounts ● 1 | Apply | Search | Appearance`) need a wrap or scroll rule (MINOR-5).

**H7 Copy.** Copy is mostly plain words that say what happened and how to fix it. Exceptions are in MINOR-6.

## 2. Issues

**BLOCKING-1 · §8 Order: B and C depend on each other, and the merge order A → C → B can't work.** C merges
first but imports `connections.js` / `connections_api.js`, which only B creates. Either the stub sits at the
same path (then C and B collide) or C's imports point at a stub path that B must later edit (C's files). B, in
turn, needs C's `useView`. Fix: a tiny lane **0** (one engineer, merged right after T0) owns the three shared
contract files: `route.js` (`parseHash`, `hashFor`, `useView`), `connections.js` (code → copy, state → chip,
`applySteps`) and `connections_api.js`. After that, A, B and C are truly independent and can merge in any order.
Give `style.css` (chip tones, the `--bottom-nav-h` variable) to lane 0 as well.

**MAJOR-1 · §2, §3.3: the AI switched off has no state.** `backends.build` returns `OffBackend` when
`budget.enable_llm` is false or the backend is `off` (`backends.py` `build`, `OffBackend:80-84`). Its `available` is
False and it sets no `unavailable_code`. With today's mapping that becomes `attention` and a permanent banner on
every page for an owner who chose no AI. Add `paused · ai_off` ("Local AI is off in config.yaml
(budget.enable_llm). Runs work without it; screening and auto-apply wait for it.") and set
`unavailable_code = "off"` in `OffBackend`. Also: a `-cloud` tag gives `local: false`, so the card must not say
"on this PC" for it (D-107).

**MAJOR-2 · §3.2: `connections.py` imports `account_view` from a peer router.** The minimum safe fix: don't import
it. `compose()` already takes the raw `mail_accounts` rows for `retry_after`, so map them there with the
contracts web may import (`WEB_MAY_IMPORT`, `tests/test_layering.py:74-79`): `SyncCode`, `SYNC_TEXTS` and
`CONSENT_VERSION` from `mailstatus.contracts`, plus a four-line local `_sync_text`. Then add one lane-A test
asserting that the hub's `message` equals `account_view(row)["message"]` for every `SyncCode`. That pins
equivalence in a test that fails on drift, without a runtime dependency on peer code.

**MAJOR-3 · §4.2: "Fill in your application details" vanishes before Q-110 merges.** That is the most important
step for A4. Source it from the existing `GET /api/applicant` (`missing`, `completeness`; `routers/applicant.py:129-135`,
as `Profile.vue:136-143` already does). Use `/api/apply/status` only for `busy` and `mode`.

**MAJOR-4 · §5 A14: the bottom bar hides the Profile Save bar and the toasts at 390 px.** Specify a
`--bottom-nav-h` variable and `padding-bottom: calc(var(--bottom-nav-h) + env(safe-area-inset-bottom))` on
`main`. Offset `.save-bar` (`bottom: var(--bottom-nav-h)`) and `.toast` the same way. Add `ToastHost.vue` to lane C.

**MAJOR-5 · §8: no lane owns the existing tests that break.** `web/tests/Settings.test.js`, `Profile.test.js`,
`Applications.test.js`, `Overview.test.js`, `App.test.js` and `extensibility.test.js` assert today's sections,
links and hash rules, so the plan's own `Verify:` (`npx vitest run`) fails. The engineer scope hook refuses `tests/`.
Add tester lanes T-B and T-C (and T-A for `tests/test_connections*.py`) with the named files.

**MAJOR-6 · §1: the "Settings → Apply" mailbox hint stays false.** `apply/contracts.py:175` says "Set up the mailbox in
Settings → Apply", but §4.1 puts the Application mailbox in **Accounts**. Either show a mailbox readiness row with a
link in the Apply view, or request a peer copy change. The claim "naming the views makes those hints true"
(§1 reason 1) is false for this one.

**MINOR**
1. §3.4: state that `check_failed` never carries exception text (a `VaultError` names the service and host, `vault.py:84-85`), and add `/api/connections` to ADR-0009 action item 2 (the marker-value scan).
2. §3.3: set the "probe in flight" flag inside the same lock as the staleness check, and clear it in `finally`.
3. §3.3: close the probe backend's client (`backend._http.close()` in `finally`), or add `backends.probe(budget) -> (ok, code, model)` in `backends.py` so no backend object is built.
4. §2 Edge `in_use`: it reads only the web JobManager (`jobs.py:347-350`). A CLI-started `apply`, the main path until Q-110, also holds the profile. Also check Chromium's `lockfile` in the profile dir. Separately, a dir that exists is "Ready", not "Connected" (it says nothing about sign-ins).
5. 390 px: state a ≥ 44 px minimum under 640 px for every new control; wrap `<code>` (`white-space: pre-wrap; overflow-wrap: anywhere`); let the four Settings view tabs wrap.
6. Copy: "no CAPTCHA wait" is opaque and must not read as CAPTCHA handling. Use "Stops at a human check" or "Waits up to N s for you at a human check". The banner's "Fix it" overpromises in Wave 1, where the fix is a CLI command: use "See how to fix". Count only required steps in "n of m done", so "5 of 9" never stalls on optional Gmail.
7. §2 Employer `creating`/`unknown` → `connected` shows green for a sign-up that may have failed (`unknown` = an exception after the click, `apply/contracts.py:618`). Use a neutral "Not confirmed" chip; that keeps the design's own "never a false all-good".
8. §2 Gmail `timer_off` keys on `next_at` being null. Use `timer_running` (`mailsync.py:137-139`) so a sync in flight never reads as "off". With MailCard embedded unchanged, its paused message repeats the card-header line; show it once (via R2's `embedded` prop). There is one `gmail:<id>` item per mailbox but one card: say which line shows when there are two.
9. Citations drifted after the Q-45 merge: `with_settings` is now `config.py:162`; R1's line is now `Inbox.vue:461` ("You're all caught up."); `mailstatus/contracts.py:30-34` is `AccountState`, and the codes are `SyncCode` from line 37. Also define what an unknown `#/settings/<view>` does (it falls back to the default view; `route.js:6-8` today rewrites any sub-path to the first tab).

## 3. Checklist (`05` §5)

| Item | Result |
|---|---|
| Every requirement mapped | Yes (§7). A4 is partly unmapped (MAJOR-3) and the off-AI state is missing (MAJOR-1) |
| Depends only on contracts and foundation | No, until MAJOR-2 is fixed (a router import into a pure module) |
| Degradation and every code defined | `OffBackend` is missing (MAJOR-1); `check_failed` and 404 fallbacks are defined |
| Nothing contradicts `01` / D-190..D-193 | Holds: no login, no secret out, no apply start, emails in full |
| Lanes disjoint, ordered, no design decision left | Disjoint as listed, but in a cycle (BLOCKING-1); `style.css`, `ToastHost.vue` and the tests have no owner (MAJOR-4, MAJOR-5) |
