# ADR-0009: No stored secret travels from the server to the browser (D-191)

**Status:** Accepted (Coordinator decision D-191, 2026-11-11). **Date:** 2026-11-11. **Deciders:** Coordinator; the apply/credentials owner (peer session jobscraper-48) informed. **Amends:** apply_design §14.3 (row `POST /api/apply/accounts/{id}/password`). The "Copy password" mentions in §10.3 and §14.4 are superseded by the same decision. **Design:** `docs/architecture/q100_ui_design.md` §6.

## Context

F-35's fallback for getting ATS passwords into Edge had two parts: "Export new passwords for Edge" (a CSV) and a per-account **Copy password**. apply_design §14.3 specified `POST /api/apply/accounts/{id}/password`, which returns the password once with `Cache-Control: no-store`, and §10.3 had the UI copy it to the clipboard. That endpoint was never built: no router reads `ats_accounts` (see `accounts_ux_current_state.md` §2).

The Q-100 hub now shows the employer accounts in the web app, so whether to build it has to be decided. The forces:
- **NF-02:** secrets live only in Windows Credential Manager, and never in logs or in prompts.
- **The app has no login** (D-190). A response body is readable by the browser, by its extensions and by anything that can drive it, and a clipboard is readable by every process in the session.
- **The web app is reachable from any local process.** The Host and cross-site checks (`web/api.py:85-89,249-250`) stop other websites, not local software.
- **Precedent:** MailCard already takes an app password write-only. The input has no `v-model` and is cleared before sending (`web/src/components/MailCard.vue:11-14`). The route reads the raw body and never echoes it (`web/routers/mail.py:8-11,59-79`), and the password reaches the vault only through a child process's stdin (`web/mailsync.py:254-259`).

## Decision

1. **No endpoint returns a stored secret, or any derivative of one** (value, length, hash, masked form). This covers ATS passwords, IMAP app passwords and anything else under `jobscraper:*` in Credential Manager. Responses may carry `has_password: bool` and nothing more.
2. **Write-only entry stays allowed** (browser → server → vault). It uses the MailCard pattern: the raw body is parsed, the value is wrapped in `Secret` straight away, it goes to a child CLI process on stdin, it is tested before storing where a test exists, and only fixed error text comes back.
3. **Reading a stored password stays outside the web app.** The owner has two routes: `python -m jobscraper accounts export-edge` (CSV for Edge's import, zero-overwritten after import, `cli.py:1176-1204`), and Windows' own Credential Manager, which asks for the Windows password before it shows a value.
4. **The hub's replacement for Copy password is "Open sign-in page in the apply browser"** (Wave 2, q100 design §6 G6). It opens the tenant's sign-in page in the JobScraper Edge profile. Edge does not fill the password there (sync is off, `apply/browser.py:87`). The owner pastes it from their own Edge, after the CSV import, or from Credential Manager.

## Options considered

| | A: Copy password endpoint (as planned) | B: Write-only web; reading via CLI/OS (chosen) | C: Show the password in the page behind a confirm |
|---|---|---|---|
| Complexity | Medium (no-store, clipboard, audit) | Low (nothing to build for reading) | Medium |
| Exposure | Response body + clipboard, any local process | Credential Manager only; the CSV for at most an hour | Body + DOM + screen |
| Convenience | Best | One CLI command or an OS dialog | Good |
| Fits D-190 (no app login) | Poorly: the gate would be a click | Yes | Poorly |

**A**'s gain is a few seconds per manual sign-in, which happens rarely: JobScraper signs in itself, and the owner steps in only after `signin_failed`. Its cost is a standing secret-read API on an unauthenticated local server. **C** has every risk of A and puts the password on screen as well. **B** keeps the web app's secret surface write-only, the same as F-50's.

## Consequences

- Easier: one rule for every route and test ("no response contains a vault value"). The tester can enforce it by scanning response bodies with a stub vault that holds marker values.
- Harder: the owner can't copy an ATS password from the browser. The hub's Employer accounts help text names the two reading routes.
- `has_password` probes read the secret into server memory for a moment (`vault.get(...) is not None`, as `web/routers/mail.py:103-106` already does). A later `vault.exists()` helper owned by the peer would avoid that. This is not required.
- Revisit if an app lock (D-190 §6, an owner option) is ever built. Even then, prefer step-up auth plus a CLI reveal over a web reveal.

## Action items

1. [x] apply_design §14.3: replace the Copy password row with a pointer to this ADR.
2. [ ] Tester: add a "no secret in any `/api` response" check to the Q-100 test plan, explicitly including `GET /api/connections`. The check uses a stub vault holding marker values, calls GET on every route, and asserts that no marker, `vault_service` value or exception text appears in any response body (q100 design §3.4, T1).
3. [ ] Hub copy (q100 §5.4) names the reading routes; no "Copy" button anywhere.
