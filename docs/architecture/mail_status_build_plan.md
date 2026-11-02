# Application status from email: build plan (F-50, Q-60)

Architect, 2026-11-02. Design: `mail_status_design.md` (**MS §n**); ADR-0007. Conventions as `docs/planning/apply_build_plan.md` §0:
- A WP is ≤ ~1 day, ≤ ~8 files, one lane, one `Verify:` command.
- Engineers don't write `tests/**`; the tester's files are skip-clean until their module exists.
- Every branch starts from `int/Q-60-mail-status` (`git switch -c <branch> int/Q-60-mail-status`) and merges back into it. The Coordinator merges the integration branch into `personal` only with the owner's go-ahead (D-90).
- NF-08: a copied database, port 8768, **`JOBSCRAPER_MAIL_SYNC=0`**. No real mailbox is read before the owner's go-ahead (MS §15 owner item 4).
- No WP needs a design decision: if one seems to, the engineer logs a `question` in their outbox and builds what MS states.

## 1. Lanes (≤ 3 engineers at once + tester)

| Lane | Branch | Own files | Shared-file blocks |
|---|---|---|---|
| **S** stage (pure) | `eng/Q-60-S-stage` | `src/jobscraper/mailstatus/__init__.py`, `contracts.py`, `rules.py`, `match.py`, `transition.py`, `model.py` (all new) | none |
| **I** IMAP + SPA | `eng/Q-60-I-imap` | `src/jobscraper/imapread.py` (new), `src/jobscraper/apply/mail.py`; `web/src/components/MailCard.vue`, `MailSuggestions.vue`, `MailEvidence.vue` (new), `web/src/tabs/Settings.vue`, `web/src/tabs/Applications.vue`, `web/src/stages.js`, `web/src/style.css`, `web/src/api.js` | none |
| **F** flow, store, CLI, web backend | `eng/Q-60-F-flow` | `src/jobscraper/mailstatus_flow.py`, `src/jobscraper/web/mailsync.py`, `src/jobscraper/web/routers/mail.py` (all new); `store.py`, `config.py`, `config/config.yaml`, `cli.py`, `web/api.py`, `web/routers/applications.py` | `store.py` F-block appended at the end of `SCHEMA` and of `Store`, plus the `_write_status` refactor of `set_application_status` |
| **T** tester | `test/Q-60-mail-oracles` | `tests/**`, `web/tests/**` | — |
| **R** researcher | `res/Q-60-mail-rules` | `config/mail_rules.yaml` (new; needs a scope grant), `docs/research/mail_status_brief.md` (appendix) | — |
| **P** planner | `plan/Q-60-prd` | `docs/prd.md`, `docs/DESIGN.md`, `docs/OVERVIEW.md` | — |

**Disjointness:** S, I and F share no file. Lane I's `apply/mail.py` and `Applications.vue` may also be touched on `personal` by the concurrent session; the Coordinator resolves the text merge (both changes are small). `config/mail_rules.yaml` belongs to R alone; S and F build against the tester's `tests/fixtures/mail/rules_min.yaml`.

**Order:**
- **S:** S0 → S1 → S2 → S3.
- **I:** I1 → I2 → U1 → U2. U1 and U2 build against the MS §11.1 shapes with mocked fetches.
- **F:** F1 → F2 → F5a → (S and I1 merged) F3 → F4 → F5b.
- **T:** T0 (merges with S0) → T1 → T2 → T3 → T4 → T5 → T6.
- **R:** R1 any time; R2 needs the owner's consent.
- **P:** P1 any time.
- Integration: X1.

## 2. Tester

#### WP-T0 · Layering sets + contracts oracles
- **STATUS:** READY (merges together with WP-S0; ADR-0007 action 1)
- **Inputs:** MS §2.2 (rules 1–6), §3.
- **Files:** `tests/test_layering.py`, `tests/test_mail_contracts.py`.
- **Do:** the set edits and the new `test_mail_modules_never_write_the_mailbox` (MS §2.2 rule 5); self-check cases (rule 6). Contracts: `CONTRACT_VERSION == 1`; every `SyncCode` except `OK` has a `SYNC_TEXTS` entry; every `SUGGEST_REASONS` member plus `FORWARD` has a `REASON_TEXTS` entry; the two Reason sets are disjoint; a minimal class with the five `MailTransport` methods passes `isinstance`; `AccountReport().counts` has every `COUNT_KEYS` key and isn't shared between instances; `contracts.py` imports only the stdlib.
- **Verify:** `python tests/run_tests.py -k layering` and `-k mail_contracts`
- **Done when:** green with S0; red without the sets (prove it once by hand).

#### WP-T1 · Synthetic fixtures and the fake IMAP server
- **STATUS:** READY
- **Inputs:** MS §5.2–§5.6, §6.1, §13; MB §3–§4 (shapes only).
- **Files:**
  - `tests/mail_support.py`: `FakeImap`, which is patchable as the `imaplib.IMAP4_SSL` factory. It speaks LOGIN, CAPABILITY (`X-GM-EXT-1`, configurable), LIST with special-use flags (localised names, a hidden-`\All` variant), EXAMINE (UIDVALIDITY, UIDNEXT), UID SEARCH (`UID n:*` with the RFC "`*` includes the highest" behaviour, `SINCE`, `X-GM-MSGID`), UID FETCH (the MS §5.3 items, `BODY.PEEK[]`), NOOP and LOGOUT. It **records every command**; it can fail a login with each Gmail error text, drop the connection after N commands, and change UIDVALIDITY between sessions.
  - `tests/fixtures/mail/rules_min.yaml`: a small valid rules file.
  - `tests/fixtures/mail/golden/*.eml` and `tests/fixtures/mail/golden.yaml` (expected `skip|category|match|change`).
- **Do:** at least 3 golden cases per category, plus the tricky cases of MB §4: a neutral subject with "log in to view", a volume disclaimer in an acknowledgement, a talent-community newsletter, a job alert, job-board mail, verification and security-code mail containing "confirm", a reminder, a reschedule, recruiter outreach, `Auto-Submitted: auto-replied` versus `auto-generated`, own sent mail, a Chinese-language rejection, a "pleased to offer you an interview", HireVue on-demand versus live, kept-on-file alone and with a rejection, offer from Spam, offer with `dmarc=fail`. Synthetic only: employers "Example Corp" or "Northwind" on `example.com`/`example.org`; real platform domains. Grep the tree for the owner's values before committing.
- **Verify:** `python tests/run_tests.py -k mail_fixtures`
- **Done when:** every `.eml` parses, `golden.yaml` lists each file, and the deny-list scan is clean.

#### WP-T2 · Rules, gates and classifier oracles
- **STATUS:** READY (skip-clean until S1)
- **Inputs:** MS §6.1–§6.4.
- **Files:** `tests/test_mail_rules.py`.
- **Do:**
  - every golden case against `rules_min.yaml` **and** against the real `config/mail_rules.yaml` once R1 lands (skip while absent);
  - each validation error names its entry;
  - the gate order of MS §6.2;
  - `dominates` resolution: a winner, a conflict giving `conflict:a+b`, and `portal_update` dropping out;
  - the quote is ≤ 200 characters and present;
  - the ≥ 20% non-Latin rule sets `status_words`;
  - the bare word "confirm" never trips the account gate.
- **Verify:** `python tests/run_tests.py -k mail_rules`
- **Done when:** green after S1 (and after R1 for the real-file half).

#### WP-T3 · Matcher, transitions and model-parse oracles
- **STATUS:** READY (skip-clean until S2/S3)
- **Inputs:** MS §7, §8, §6.5.
- **Files:** `tests/test_mail_match.py`, `tests/test_mail_transition.py`, `tests/test_mail_model.py`.
- **Do:**
  - **Matcher:** each signal alone and combined; two applications at one employer separated by role and by req id, and left ambiguous without either; employers across two companies (tie → AMBIGUOUS); a common-word name in the body only → no signal; a Workday tenant from the local part; thread first; a saved role matched. **E1:**
    - an Oleeo sender `examplebank.tal.net` matches "Example Bank" by compact name, with no attempt row;
    - a Workday local part equal to the compact company name matches;
    - `tal.net` itself (not a strict subdomain) gives no tenant;
    - `tenants_from_hosts` takes the tenant from a `*.myworkdayjobs.com` posting URL and a `*.tal.net` careers URL;
    - a loader error when both tenant flags are true.
  - **Transitions:** every row of the MS §8 table, including 4 (candidates dropping out), 6 (owner newer), 7 (reopen versus terminal), 9 (backwards → NONE, no suggestion), and 11a–e in order; `to_apply → applied` gives AUTO.
  - **Model parse:** a valid reply, bad JSON, a category outside the enum, an empty quote, a quote not in the message → UNKNOWN; the prompt holds the email only (no profile value) and every URL appears as `[link]`; `SCHEMA` enum == `Category` values.
- **Verify:** `python tests/run_tests.py -k mail_match` and `-k mail_transition` and `-k mail_model`
- **Done when:** green after S2 and S3.

#### WP-T4 · Transport oracles (imapread + apply/mail)
- **STATUS:** READY (skip-clean until I1/I2)
- **Inputs:** MS §5.2–§5.7, §12 (login codes).
- **Files:** `tests/test_imapread.py`, `tests/test_apply_mail.py` (cases appended).
- **Do:**
  - **The command log:** no STORE, COPY, MOVE, EXPUNGE, APPEND, SELECT without read-only, or `BODY[` without `.PEEK`, ever, across a full scan and fetch; `_ReadOnly` has no such methods.
  - **Special-use folders:** localised names; the `\All`-hidden fallback to INBOX with note `all_mail_hidden`; `\Junk` hidden.
  - **`plan_scan`:** first sync (empty and non-empty); resume; the `n:*` gotcha drops `uid <= last`; a UIDVALIDITY change → RESCAN; the cap → `complete=False` with no `end_cursor`; `end_cursor = max(last, UIDNEXT − 1)`.
  - **Parsing and codes:** headers parsed into `MailHeader` (decoded subject and display name, `auth` from `Authentication-Results`: dmarc pass, aligned DKIM, fail, none); the body has `[link]` in place of URLs plus the calendar flag; `login_code` maps each Gmail error text and never returns server text; `refind` searches X-GM-MSGID in ALL, then JUNK.
  - **apply/mail:** `apply/mail.py` reads the special-use Spam name, falls back to `[Gmail]/Spam`, and its aliases equal the `imapread` functions.
- **Verify:** `python tests/run_tests.py -k imapread` and `-k apply_mail`
- **Done when:** green after I1 and I2; the existing `test_apply_mail.py` cases stay green.

#### WP-T5 · Store and flow oracles
- **STATUS:** READY (skip-clean until F1/F3)
- **Inputs:** MS §5.1, §5.4, §5.5, §8, §9, §10.2, §10.4, §12, §13.
- **Files:** `tests/test_store_mail.py`, `tests/test_mail_flow.py`, `tests/test_config_mail.py`.
- **Do:**
  - **Config:** `MailStatusConfig` defaults and clamps (`interval_min` limited to 5–120); unknown keys ignored; `assessment` in `application_statuses`; `mail_rules_path`.
  - **Store:**
    - `mail_record` atomicity: patch the cursor upsert to raise, and the message row, event and evidence are all absent;
    - the re-check inside `mail_record` gives `owner_newer`;
    - the lease: a second `begin` → None; a stale lease → `abandoned`;
    - `mail_accept` (`changed` 409 cases, an ambiguous pick), `mail_undo` (`not_latest`), `mail_dismiss`, suggestions marked `superseded`;
    - `delete_application` and `relink_orphan_applications` cascade; `mail_account_delete` keeps auto and accepted evidence; `mail_purge` windows;
    - `application_events` returns `by` and `evidence_id`; `SCHEMA_VERSION >= 5`.
  - **Flow** (`FakeImap` + a fake backend + a temp DB):
    - first sync, then resume with no reprocessing; a UIDVALIDITY change between runs; a Spam-to-All-Mail move deduped;
    - a crash mid-scan (kill after N commands), with the next run continuing exactly after the last stored message;
    - the body cap and deadline → `partial`;
    - model unavailable → `pending_model` → retried → expired into a `model_unavailable` suggestion; `--defer-model`;
    - login refused → PAUSED and no retry on the next timer-triggered sync; network → backoff `retry_after`;
    - `rules_invalid`;
    - **canary:** a marker string in a subject, a body, a display name and a sender address never appears in `caplog`, the CLI stdout or the job log, and neither does the account address.
- **Verify:** `python tests/run_tests.py -k store_mail` and `-k mail_flow` and `-k config_mail`
- **Done when:** green after F1, F2 and F3.

#### WP-T6 · CLI, web and SPA oracles
- **STATUS:** READY (skip-clean until F4/F5/U1/U2)
- **Inputs:** MS §4, §10, §11.
- **Files:** `tests/test_cli_mail.py`, `tests/test_web_mail.py`, `web/tests/MailCard.test.js`, `web/tests/MailSuggestions.test.js`.
- **Do:**
  - **CLI:** `mail accounts add --password-stdin --json` stores nothing on a login failure and prints only `{"result": code}`; `mail sync` prints no address.
  - **Web:**
    - the password appears in no response or log on 200, 400, a malformed body and wrong types;
    - `create_app()` starts no timer thread by default;
    - `POST /api/mail/sync` → 409 while a child runs;
    - `DELETE` keeps a shared vault entry and deletes an unshared one (keyring swapped for a memory backend);
    - the cross-site guard covers the new routes;
    - `gmail_url` shape; events carry `by` and `mail`.
  - **Vitest:** the card's states (none, application mailbox offered, ok, paused with text, off, notes, running); the consent checkbox gates Connect; the suggestion actions (Set to, Dismiss, Got it, ambiguous select); the badge and Undo; the 409 messages.
- **Verify:** `python tests/run_tests.py -k cli_mail` and `-k web_mail` and `cd web; npx vitest run tests/MailCard.test.js tests/MailSuggestions.test.js`
- **Done when:** green after F4, F5b, U1 and U2.

## 3. Lane S (stage)

#### WP-S0 · Contracts v1
- **STATUS:** READY. **Files:** `src/jobscraper/mailstatus/__init__.py` (a docstring only), `src/jobscraper/mailstatus/contracts.py`. **Inputs:** MS §3. **Depends on:** — (merge with T0).
- **Do:** transcribe MS §3 verbatim; the architect signs off at review.
- **Verify:** `python tests/run_tests.py -k mail_contracts` (and `-k layering` with T0)
- **Done when:** both green. **Requirements:** NF-04, F-50t.

#### WP-S1 · Rules file loader, gates, classifier
- **STATUS:** READY. **Files:** `src/jobscraper/mailstatus/rules.py`. **Inputs:** MS §6.1–§6.4. **Depends on:** S0, T1 (`rules_min.yaml`).
- **Do:**
  - `load_rules(path) -> Rules` (frozen dataclass; compiled patterns) raising `RulesError(entry_id, message)`. **E1:** the platform keys `tenant_from_local_part`, `tenant_from_subdomain` (at most one true) and `tenant_sites` (MS §6.1) are validated and kept;
  - `platform_of(h, rules) -> str`;
  - `header_gate(h, rules, *, own: frozenset[str], window_start: str, threads: frozenset[str], employer_regs: frozenset[str]) -> Optional[Reason]`;
  - `content_gate(h, body, rules, *, in_matched_thread: bool) -> Optional[Reason]`;
  - `classify(h, body, rules) -> Verdict`;
  - `quote_around(text, start, end) -> str`;
  - `needs_model(v: Verdict) -> bool`.
  - No I/O beyond reading the YAML file.
- **Verify:** `python tests/run_tests.py -k mail_rules`
- **Done when:** T2 green on `rules_min.yaml`. **Requirements:** F-50h, F-50i, F-50k, F-50t.

#### WP-S2 · Matcher
- **STATUS:** READY. **Files:** `src/jobscraper/mailstatus/match.py`. **Inputs:** MS §7. **Depends on:** S0, S1 (`Rules`).
- **Do:** `norm_company(name, suffixes)`, `norm_role(title)`, `compact(s)`, `variants(app, rules)`, `tenants_from_hosts(hosts, rules) -> tuple[str, ...]` (E1), `match(h, body, apps: Sequence[AppCandidate], rules) -> MatchResult` per the six decision steps; `signals` listed in `Signal` order. **E1:** the `tenant` signal covers `tenant_from_local_part` and `tenant_from_subdomain`, compared in compact form against `app.tenants` and every company variant (MS §7).
- **Verify:** `python tests/run_tests.py -k mail_match`
- **Done when:** T3 matcher half green. **Requirements:** F-50j.

#### WP-S3 · Transitions and the model prompt
- **STATUS:** READY. **Files:** `src/jobscraper/mailstatus/transition.py`, `src/jobscraper/mailstatus/model.py`. **Inputs:** MS §8, §6.5. **Depends on:** S0.
- **Do:**
  - `transition.py`: `build_policy(statuses, raw_mail_status_cfg) -> Policy` (drops targets missing from `statuses`); `decide(app, verdict, match, h, policy, *, candidates: Sequence[AppCandidate] = ()) -> Change`, rows 1–11 in order.
  - `model.py`: `SYSTEM`, `SCHEMA`, `MAX_TOKENS = 200`, `SEED = 7`, `user_prompt(h, body, max_chars) -> str`, `parse(reply, h, body, model_id) -> Verdict`.
  - No backend import: the flow calls `complete`.
- **Verify:** `python tests/run_tests.py -k mail_transition` and `-k mail_model`
- **Done when:** T3 green. **Requirements:** F-50k, F-50l.

## 4. Lane I (IMAP + SPA)

#### WP-I1 · `imapread.py`
- **STATUS:** READY. **Files:** `src/jobscraper/imapread.py`. **Inputs:** MS §5.2–§5.6, §12, §13; `apply/mail.py` (the helpers to move). **Depends on:** S0.
- **Do:**
  - `_ReadOnly` (MS §5.6);
  - the moved helpers: `body_text` (= `apply.mail._body`, plus a `links=False` mode that replaces URLs with `[link]`), `sender_domain`, `domain_matches`, `employer_domain`, `registrable_domain`, `host_of`, `quote_folder`, `internaldate`, `login_code(exc) -> SyncCode`;
  - `special_use_folders(conn) -> dict[MailboxRole, str]`;
  - `parse_header(meta, raw, ref, cursor_before) -> MailHeader` (with `auth_result(headers, from_reg) -> AuthResult`);
  - `plan_scan(cursor, uidvalidity, uidnext, window_start, now)`;
  - `ImapTransport(host, port, username, password: Secret, *, timeout_s=20, connect=None)` implementing `MailTransport`.
  - Imports: the stdlib, `apply.contracts.Secret`, `mailstatus.contracts`.
- **Verify:** `python tests/run_tests.py -k imapread`
- **Done when:** T4 imapread half green; `-k layering` green. **Requirements:** F-50d–g, F-50p, F-50q, F-50r.

#### WP-I2 · `apply/mail.py` on `imapread`; the Spam fix
- **STATUS:** READY. **Files:** `src/jobscraper/apply/mail.py`. **Inputs:** MS §5.7. **Depends on:** I1.
- **Do:** aliases (`_body = imapread.body_text`, and so on) so the names stay importable; `_scan`/`newest_from` read `INBOX` plus the `\Junk` folder found by `special_use_folders`, falling back to `FOLDERS[1]`; the module docstring updated. No F-36 behaviour change.
- **Verify:** `python tests/run_tests.py -k apply_mail`
- **Done when:** the existing cases and T4's appended ones are green. **Requirements:** MB §7 item 8, D-91 e.

#### WP-U1 · Settings: the email card
- **STATUS:** READY. **Files:** `web/src/components/MailCard.vue`, `web/src/tabs/Settings.vue`, `web/src/api.js`. **Inputs:** MS §4, §11.1–§11.3. **Depends on:** — (mocked API).
- **Do:**
  - the "Email" section with the card: the application mailbox first, the connect form, the consent box gating Connect, rows with the switch, the status line, notes, Check now, Change app password, and Disconnect with its dialog;
  - polling `GET /api/mail` every 5 s while `sync.running`, else on focus;
  - the password field is cleared after every attempt, and the password is never stored in component state after submit.
- **Verify:** `cd web; npx vitest run tests/MailCard.test.js`
- **Done when:** T6 card tests green; `npm run build` passes in the worktree (the bundle is rebuilt only in the main checkout, X1). **Requirements:** F-50a–c, F-50o.

#### WP-U2 · Applications: suggestions, evidence badge, `assessment`
- **STATUS:** READY. **Files:** `web/src/components/MailSuggestions.vue`, `web/src/components/MailEvidence.vue`, `web/src/tabs/Applications.vue`, `web/src/stages.js`, `web/src/style.css`. **Inputs:** MS §8, §11. **Depends on:** U1 (`api.js` helpers).
- **Do:**
  - the suggestions panel (hidden when empty) with Set to, Dismiss, Got it, the ambiguous select and Open in Gmail;
  - the "From email" badge plus `MailEvidence` in the History timeline, with Undo when `undoable`;
  - a refetch after each action;
  - `assessment: 'Assessment'` and the `--stage-assessment` colour rules.
- **Verify:** `cd web; npx vitest run tests/MailSuggestions.test.js tests/Applications.test.js`
- **Done when:** green, including the existing `Applications.test.js`. **Requirements:** F-50l–n.

## 5. Lane F (flow, store, CLI, web backend)

#### WP-F1 · Store block
- **STATUS:** READY. **Files:** `src/jobscraper/store.py`. **Inputs:** MS §9, §8. **Depends on:** —.
- **Do:** the five tables in `SCHEMA` (appended); `SCHEMA_VERSION = 5`; every method in the MS §9 table; `_write_status`, factored out of `set_application_status`, which then calls it and commits (same behaviour); `mail_run_begin` with `BEGIN IMMEDIATE`; `application_events` with `by` and `evidence_id`; the cascades. **E1:** `mail_match_context` returns raw `tenant_hosts`: the attempt `tenant_host` values plus the hosts of `jobs.url`, `applications.url` and `companies.careers_url`, so hand-made applications get tenants (MS §9).
- **Verify:** `python tests/run_tests.py -k store_mail` (and the full suite: `python tests/run_tests.py`)
- **Done when:** T5 store half green; the full suite green. **Requirements:** F-50c, e, l–n, s.

#### WP-F2 · Config and the `assessment` status
- **STATUS:** READY. **Files:** `src/jobscraper/config.py`, `config/config.yaml`. **Inputs:** MS §10.4. **Depends on:** —.
- **Do:** `MailStatusConfig.from_raw` (defaults, clamps, unknown keys ignored); `cfg.mail_status`; `cfg.mail_rules_path`; the `mail_status:` block in `config.yaml`; `assessment` in `applications.statuses` and in the `application_statuses` default list.
- **Verify:** `python tests/run_tests.py -k config_mail` and then the full suite (`python tests/run_tests.py`)
- **Done when:** T5's `test_config_mail.py` is green, and the full suite (the stats and Applications tests included) is green with the new status. **Requirements:** F-50d, F-50l.

#### WP-F5a · Web backend, part 1: runner and router on the store
- **STATUS:** READY. **Files:** `src/jobscraper/web/mailsync.py`, `src/jobscraper/web/routers/mail.py`, `src/jobscraper/web/api.py`, `src/jobscraper/web/routers/applications.py`. **Inputs:** MS §4, §10.1, §11.1. **Depends on:** F1, F2.
- **Do:**
  - `MailSyncRunner` (timer, `trigger`, `connect`/`use_application`/`set_password` via a short child with the password on stdin, `status`, `stop`, logs in `data/jobs/mail/`);
  - `create_app(..., mail_timer=False)` creates `app.state.mail` and starts the timer only when true;
  - every route in MS §11.1; the password routes parse JSON by hand and wrap the password in `Secret`;
  - `gmail_url`; `applications.py` adds `by` and `mail` to events.
  - The child command is whatever the injected `command` builder returns, so the tests stub it.
- **Verify:** `python tests/run_tests.py -k web_mail`
- **Done when:** the T6 web cases that don't need F3/F4 are green (stubbed child). **Requirements:** F-50a–d, F-50m–o, NF-02.

#### WP-F3 · `mailstatus_flow.py`
- **STATUS:** READY (starts after lanes S and I1 merge into the integration branch). **Files:** `src/jobscraper/mailstatus_flow.py`. **Inputs:** MS §4, §5.1, §5.4, §5.5, §12, §13. **Depends on:** S0–S3, I1, F1, F2.
- **Do:**
  - `sync(cfg, *, trigger, account_id=None, defer_model=False, store=None, transport_factory=None, backend=None, now=None) -> SyncReport`;
  - `connect(cfg, *, address=None, password=None, use_application=False, consent_version, store=None, transport_factory=None, now=None) -> tuple[SyncCode, Optional[int]]`;
  - `set_password(cfg, account_id, password, ...) -> SyncCode`.
  - The lease and heartbeat; the account selection rules; `own` addresses (accounts, `apply.mail`, the profile contact via `applicant.py`); the per-message order of MS §5.4; the model call through `backends` (`format=SCHEMA`, temperature 0, seed 7); the budgets, deadline and caps; the pending retry; the backoff arithmetic; the logging per MS §13 (ids, counts, codes, domains only).
- **Verify:** `python tests/run_tests.py -k mail_flow`
- **Done when:** T5 flow half green, including the canary. **Requirements:** F-50a, d–s.

#### WP-F4 · CLI verbs
- **STATUS:** READY. **Files:** `src/jobscraper/cli.py`. **Inputs:** MS §10.3, §4. **Depends on:** F3.
- **Do:** `mail sync` and `mail accounts list|add|set-password|on|off|remove` (`--password-stdin`, `--json`, `--consent`, `--use-application`); `CONSENT_TEXT` plus a `y` prompt for the interactive add; exit codes per MS §10.3; the existing `mail set-password` and `mail test` unchanged.
- **Verify:** `python tests/run_tests.py -k cli_mail`
- **Done when:** T6 CLI cases green. **Requirements:** F-50a, F-50o.

#### WP-F5b · Web backend, part 2: real children
- **STATUS:** READY. **Files:** `src/jobscraper/web/mailsync.py`, `src/jobscraper/cli.py` (`cmd_web` passes `mail_timer`). **Depends on:** F4, F5a.
- **Do:** the default command builder runs the real CLI verbs; `cmd_web` passes `mail_timer=os.environ.get("JOBSCRAPER_MAIL_SYNC", "1") != "0"`; `--defer-model` from `JobManager.current()`; `catchup_delay_s` after `partial`.
- **Verify:** `python tests/run_tests.py -k web_mail`
- **Done when:** T6 web green; a dev instance on 8768 with `JOBSCRAPER_MAIL_SYNC=0` serves `GET /api/mail` from a copied database. **Requirements:** F-50d.

## 6. Researcher, planner, integration

#### WP-R1 · `config/mail_rules.yaml` v1
- **STATUS:** READY after the Coordinator grants the scope (ADR-0007 action 3). **Inputs:** MS §6.1 schema, §6.4; MB §3–§4.
- **Do:** platforms (every MB §3 row, with `kind`; **E1:** Workday with `tenant_from_local_part: true, tenant_sites: [myworkdayjobs.com]`, and Oleeo `{id: oleeo, kind: ats, domains: [tal.net], tenant_from_subdomain: true, tenant_sites: [tal.net]}`, found by R2), job boards, company suffixes, common-word names, bulk, the four gate lists, the phrases per category (MB §4 high-precision column as regexes; HireVue on-demand under assessment, live under interview; "pleased to offer you" with `(?!\s+(an?\s+)?(interview|assessment))`), weak words, `dominates` per MS §6.1. Public data only.
- **Verify:** `python tests/run_tests.py -k mail_rules` (the real-file half of T2)
- **Done when:** the file loads and every golden case passes.

#### WP-R2 · Header-only sender and authentication spike (owner consent required; MB §7 item 1)
- **STATUS:** DONE (Coordinator, 2026-11-02; results in `comms/outbox/coordinator.md`): special-use flags present, X-GM-EXT-1 advertised, every ATS sender passed DKIM, SPF and DMARC (`require_auth: true` stands), Oleeo `*.tal.net` found (E1).
- **Do:** with the owner's go-ahead, a header-only count over the application mailbox: From registrable domains with counts, and the share of `AuthResult.PASS` per platform. No subject, address or content enters the repo; the result is a table in `docs/research/mail_status_brief.md` (appendix) with domains and percentages only.
- **Feeds:** R1 curation; the `require_auth` default (MS §15 R2).
- **Done when:** the appendix is committed and R1 is updated.

#### WP-P1 · PRD and DESIGN.md
- **STATUS:** READY. **Inputs:** MS §1, §2.3. **Files:** `docs/prd.md`, `docs/DESIGN.md`, `docs/OVERVIEW.md`.
- **Verify:** `git diff --stat int/Q-60-mail-status -- docs/prd.md docs/DESIGN.md docs/OVERVIEW.md` (docs only; the reviewer checks it against the MS §2.3 list)
- **Done when:** F-50a–t are in the PRD; the KA-3 row, NF-02, NF-04 and §8.2 are updated; the module map shows `imapread.py`, `mailstatus/` and `mailstatus_flow.py`, with the same sets as `tests/test_layering.py`.

#### WP-X1 · Integration (Coordinator)
- **Merge order into `int/Q-60-mail-status`:** T0 + S0 → T1 → S1–S3 and I1–I2 (with T2–T4) → F1, F2, F5a → F3 → F4 → F5b (with T5, T6) → U1, U2 → R1 → P1.
- **Then:**
  1. the full suite, `cd web; npx vitest run`;
  2. a dev instance on 8768 with `JOBSCRAPER_MAIL_SYNC=0` and a copied database: Settings shows the card; `mail sync` against `FakeImap` in tests only;
  3. with the owner's go-ahead (MS §15 owner item 4), the first real sync from the owner's click, then a row-by-row look at the changes and suggestions with the owner;
  4. back up the live database, merge into `personal`, `npm run build` **in the main checkout**, and smoke-check `personal`.
- **Done when:** the owner has seen one real sync's results; `02_status.md`, the queue and the handover are updated.

## 7. Effort

S ≈ 3 days, I ≈ 3.5 days (I1 1.5, I2 0.5, U1 1, U2 1), F ≈ 4.5 days, T ≈ 5 days, R1 0.5 day. Critical path: F1 → F2 → F5a → (S, I1) → F3 → F4 → F5b. Lanes S and I finish before F3 starts, so the three engineer lanes overlap for about three days.
