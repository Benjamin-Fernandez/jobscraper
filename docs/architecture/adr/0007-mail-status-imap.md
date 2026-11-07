# ADR-0007: Application status from email reads Gmail over read-only IMAP, in its own stage, synced by a CLI child the web app starts

**Status:** Proposed (stage-E review pending)
**Date:** 2026-11-02
**Deciders:** architect; Coordinator at stage E; owner for the merge (D-150)
**Relates to:** F-50 (`mail_status_design.md` §1), D-52, D-72, D-85, D-150, D-151; ADR-0002 (vault); `docs/research/mail_status_brief.md` §1, §2; PRD NF-02, NF-04
**Numbering note:** if the concurrent session has taken 0007 on `personal` by merge time, renumber this file to the next free number and update the two references in `mail_status_design.md`.

## Context

D-150 asks for application statuses to be updated from the owner's Gmail while the app runs, from the last processed email to the newest, with the owner's permission. D-151 fixes the outcomes of stage A: IMAP with an app password, read-only, headers first, one transport boundary, special-use folders. This ADR records three structural choices those outcomes leave open.

1. **The access route.** The brief compares IMAP with an app password, the Gmail API (`gmail.readonly`) and IMAP with XOAUTH2.
2. **Placement.** Stage packages may not import each other (NF-04, `tests/test_layering.py`). The IMAP code that exists today lives in `apply/mail.py`, inside a stage, and F-50 is not part of applying.
3. **Running "while the app runs".** `web/` may not call the network. `JobManager` runs one job at a time, and a sync must not block a run or an apply attempt.

## Decision

1. **Route:** IMAP over TLS to `imap.gmail.com:993` with a Gmail app password kept in Credential Manager (`jobscraper:imap:imap.gmail.com`, user = address; ADR-0002). Only EXAMINE, UID SEARCH, UID FETCH (header items, `BODY.PEEK`), LIST, CAPABILITY, NOOP and LOGOUT are allowed, enforced by a wrapper with no other methods. The transport sits behind the `MailTransport` Protocol (`mailstatus/contracts.py`), so a `gmail.readonly` API transport can replace it without touching the stage.
2. **Placement:**
   - a new foundation module, `imapread.py`, is the only F-50 code that speaks IMAP;
   - a new stage package, `mailstatus/`, holds the contracts, rules, matcher, transitions and model prompt, all pure: no network, no SQL, no model transport;
   - a new orchestrator, `mailstatus_flow.py`, wires the vault, the transport, the store, `backends` and the stage;
   - `apply/mail.py` reuses `imapread` (helpers plus the `\Junk` lookup) and otherwise keeps its F-36 behaviour.
3. **Running:** `web/mailsync.py` holds a timer thread in the web process. It spawns `python -m jobscraper mail sync` as its own child process (not a JobManager job) at start-up plus 60 s and every 10 minutes, and on "Check now". A lease row in `mail_sync_runs`, taken with `BEGIN IMMEDIATE` and kept alive by a heartbeat, makes syncs single-flight across processes (the web timer, the CLI, a second web process). The connect test also runs in a short child process, with the password on its stdin.

## Options considered

### Route

| | A: IMAP + app password (chosen) | B: Gmail API, OAuth desktop app | C: IMAP + XOAUTH2 |
|---|---|---|---|
| Complexity | Low: stdlib `imaplib`, code and path already verified (D-52, D-72) | Medium–high: a Cloud project, a consent screen, OAuth libraries, a token store | Highest: B's setup plus IMAP |
| Owner effort | None beyond the existing app password | Initial setup; in Testing status, re-consent every 7 days (MB §1) | As B |
| Credential scope | Whole mailbox; read-only enforced by our code | `gmail.readonly`, enforced by Google | `https://mail.google.com/` (full) |
| Incremental sync | UID + UIDVALIDITY per mailbox, X-GM-MSGID dedupe | `history.list` from a `historyId` | As A |
| Dependencies | none | `google-auth`, `google-api-python-client` (or hand-rolled OAuth) | as B |
| Longevity risk | Google discourages app passwords; no withdrawal announced | Supported | Supported |

**A, pros:** no new setup or re-consent; reuses verified code; stdlib only; works offline-first. **A, cons:** a full-mailbox credential, with read-only resting on our code (mitigated by the wrapper and a static test); it breaks on a Google password change (handled by the PAUSED state) or if Google withdraws app passwords (handled by B). **B, cons:** the 7-day token expiry in Testing, or an unverified-app screen in Production; much more moving machinery for one user. **C** is rejected: the widest scope plus all of OAuth (MB §1).

### Placement

| | P1: a module inside `apply/` (`apply/mailstatus.py`), wired by `apply_flow` | **P2: foundation `imapread.py` + stage `mailstatus/` + `mailstatus_flow.py` (chosen)** | P3: all in one orchestrator module | P4: IMAP copied into the new stage |
|---|---|---|---|---|
| Layering | Allowed, but ties status tracking to the apply stage and its orchestrator | Clean: stages stay pure, the flow composes | Logic untestable apart from I/O; a 1,500-line module | Two IMAP implementations to keep read-only |
| Reuse of `apply/mail.py` | Direct | Via the foundation (helpers moved, aliases kept) | Direct import impossible (orchestrators may import stages, but logic would sit in an orchestrator) | None (duplication) |
| Merge risk with the concurrent session (editing `apply/`) | High (`apply/` and `apply_flow.py`) | Low: one small WP touches `apply/mail.py` | Low | Low |
| Parallel build lanes | Poor (one package) | Three disjoint lanes (transport, stage, flow/store/web) | One lane | Two |

P2 costs four test-set edits (§2.2 of the design) and one foundation module that does network I/O. That module has a precedent in `net.py`, and `web/` is explicitly forbidden from importing it.

### Running

| | R1: a `JobManager` kind | R2: a thread in the web process calling the flow | **R3: a web timer spawning a CLI child + DB lease (chosen)** | R4: Windows Task Scheduler |
|---|---|---|---|---|
| Blocks runs/applies | Yes (one job at a time) | No | No | No |
| Layering | OK | Violates it (web would import an orchestrator and do network I/O) | OK (same pattern as `JobManager`) | OK |
| "Only while the app runs" (D-150) | Yes | Yes | Yes | No (runs when closed); extra setup |
| Crash isolation | Yes | A crash or hang affects the web app | Yes | Yes |

## Trade-off analysis

The deciding forces are the owner's effort, reuse of a path that already works, the layering rules, and not competing with the apply run. Route A wins on effort and reuse. Its two real costs, the scope of the credential and the risk of Google withdrawing app passwords, are contained by the read-only wrapper, the static "never writes the mailbox" test, the PAUSED state, and the Protocol that keeps route B a one-module swap. P2 is the only placement that keeps every stage pure, lets three engineers work on disjoint files, and touches `apply/` in a single small WP. R3 reuses the subprocess pattern the web app already trusts, keeps the network out of the web process, and adds only a lease row.

## Consequences

- **Easier:**
  - the classifier, matcher and transitions are pure functions with table-driven tests;
  - a new sender or phrase is a data edit in `config/mail_rules.yaml`;
  - swapping to the Gmail API means one new transport;
  - `apply/mail.py` gets the `\Junk` fix for free.
- **Harder:**
  - two processes write the same SQLite database, so `mail_record` must be one short transaction and handle `database is locked` by stopping cleanly;
  - a dev instance with a copied database would read the real mailbox, so `JOBSCRAPER_MAIL_SYNC=0` for dev;
  - four layering sets change.
- **Revisit if:** Google announces the end of app passwords for consumer accounts (build the B transport: `gmail.readonly`, External app "In production", unverified, single user); the owner wants syncing while the app is closed (R4); polling becomes too slow (IMAP IDLE in the child).

## Action items

1. [ ] WP-T0 (tester) and WP-S0 (engineer) land together: the layering sets, the contracts oracles, the transcribed contracts.
2. [ ] WP-I1 `imapread.py` with the read-only wrapper; WP-I2 `apply/mail.py` on `imapread` and the `\Junk` lookup.
3. [ ] Coordinator: add `JOBSCRAPER_MAIL_SYNC=0` to the dev-instance command in `CLAUDE.md`, and add `config/mail_rules.yaml` to the researcher's scope.
4. [ ] Planner: PRD F-50, NF-02, NF-04, §8.2; `DESIGN.md` module map (design §2.3).
5. [ ] If app passwords are withdrawn: a new ADR and a `gmail.readonly` transport.
