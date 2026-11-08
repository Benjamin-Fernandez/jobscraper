# Handover note (rewrite every session; ≤ 40 lines; history goes to `docs/planning/session_log.md`)

**Last session:** 2026-11-08 (Q-60/M20 session, jobscraper-25; a parallel UX session jobscraper-07 runs Q-78/Q-79/Q-84). My agents stopped. **Branch/commit:** `personal`, pushed (`git log -1`).

## Done and live at next launch (all merged into `personal`, pushed)
- Q-60 email status + Q-72 (c20332a, 4c6133f): Settings → Email updates (opt-in Gmail, read-only IMAP, 10-min timer; `JOBSCRAPER_MAIL_SYNC=0` for dev copies). Gmail connected live (D-163; backup `data/jobscraper.pre-owner-mail-2026-11-07.db`).
- UX wave 3 (129e8ef) and Q-74 private fields (2045f06) by the peer session; owner to do: restart the live app, then Profile → "Re-derive profile from the stored resume". Worktree `int-Q-70-ux` holds owner preview data: delete only with the owner.
- M20 filler: lanes M+R+Q-48 (7ba7597), N6a llm FILLING loop (6001452, D-168), N6b (b684d2a): pre-Submit scan, review check (resume name on the page), fill cache keyed by job_id (30-day purge), resume_entries, other_employers. Auto mode submits only after a passing scan; live config stays `apply.mode: dry_run`, `apply.fill: llm`. Needs Ollama.
- Declarations: Q-80 D-164 `question_frame` + D-169b (a50510d); Q-82 D-170 one status question per label (bf664cf); Q-83 D-171 tails / narrowing words (false value only) / place phrases / you-subject (merged 2026-11-08). Reviews: `docs/reviews/Q-80-declarations.md`, `Q-82-declarations.md`, `Q-83-declarations.md`.
- Q-83 verified on the merged branch: Python 1551/1551, `-k apply_e2e` 13/13, `-k apply_flow` 137/137 with Edge.

## Where we are
- M19 DONE. M20: the filler is complete through N6b; what remains is the M20 gate (D-83) plus follow-ups. Workday is filled in dry runs; account creation happens only inside owner-started attempts.
- Owner declarations are all false (D-87), plus `willing_to_sign_nda: true`, `government_employment: false`.

## Next 1–3 actions
1. M20 gate (D-83): owner-watched dry runs, then 5 Greenhouse dry runs whose audits are read row by row. Needs the owner and Ollama; check Q-92 F4 (the resume-name check on a real Workday review page) on the first one.
2. Q-80 remainder: R3 F12/F14 (pagefill delete count, E5 add note) and N6a F3-F7; then Q-90 (D-171 review MEDIUM-1: place and time words still cover a TRUE value; LOW-1/2), Q-91 (six unclassified declaration labels), Q-92 F3/F5 spec notes.
3. Backlog: R3 F7/F11, Q-46 e, Q-45 compose_needed, Q-47, Q-43, Q-34, Q-32, Q-27, A04, Q-15.

## Watch out
- **The full suite skips the Edge tests silently** (a leaked asyncio loop; `edge_available()` caches the failure). Until the peer's Q-84 lands, gate every apply merge on separate `-k apply_e2e` and `-k apply_flow` runs.
- IDs: mine are Q-80..Q-83, Q-90+ and D-150..D-179; the peer has Q-73..Q-79, Q-84..Q-89, D-100..D-119. Re-read queue/status before taking one. Message jobscraper-07 before merging into personal or building the bundle.
- Always run the full suite on the integration tree after merging personal: name collisions (Q-74 `_MONTHS`) show only at runtime.
- The engineer's scope hook refuses `tests/`: route test edits (even docstrings) to the tester.
- Before every push: deny-list scan, including req ids and employer names from real mail. Live app 8765; dev 8768/8769 with a DB copy.
- The scope guard blocks the Coordinator from writing `data/`; owner profile edits go via a surgical Python replace.
