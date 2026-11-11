# Handover note (rewrite every session; ≤ 40 lines; history goes to `docs/planning/session_log.md`)

**Last session:** 2026-11-08 (Q-60/M20 session, jobscraper-25; a parallel UX session jobscraper-07 runs Q-78/Q-79/Q-84). My agents stopped. **Branch/commit:** `personal`, pushed (`git log -1`).

## Done and live at next launch (all merged into `personal`, pushed)
- Q-60 email status + Q-72 (c20332a, 4c6133f): Settings → Email updates (opt-in Gmail, read-only IMAP, 10-min timer; `JOBSCRAPER_MAIL_SYNC=0` for dev copies). Gmail connected live (D-163; backup `data/jobscraper.pre-owner-mail-2026-11-07.db`).
- UX wave 3 (129e8ef) and Q-74 private fields (2045f06) by the peer session; owner to do: restart the live app, then Profile → "Re-derive profile from the stored resume". Worktree `int-Q-70-ux` holds owner preview data: delete only with the owner.
- M20 filler: lanes M+R+Q-48 (7ba7597), N6a llm FILLING loop (6001452, D-168), N6b (b684d2a): pre-Submit scan, review check (resume name on the page), fill cache keyed by job_id (30-day purge), resume_entries, other_employers. Auto mode submits only after a passing scan; live config stays `apply.mode: dry_run`, `apply.fill: llm`. Needs Ollama.
- Declarations: Q-80 D-164 `question_frame` + D-169b (a50510d); Q-82 D-170 one status question per label (bf664cf); Q-83 D-171 tails / narrowing words (false value only) / place phrases / you-subject (merged 2026-11-08). Reviews: `docs/reviews/Q-80-declarations.md`, `Q-82-declarations.md`, `Q-83-declarations.md`.
- Q-83 verified on the merged branch: Python 1551/1551, `-k apply_e2e` 13/13, `-k apply_flow` 137/137 with Edge.
- Q-80 finished (merged 2026-11-08): R3 F12/F14, N6a F3-F6, review M1/M2 (D-172 file trigger, D-173 failed Add stays fail-closed). Review `docs/reviews/Q-80-flow-fixes.md`; follow-ups Q-93.
- Q-93 merged 2026-11-10: D-174 (a failed Add stops even when optional), D-175 (file-picker words incl. résumé/CV/document, title; skip log line), pick-path "model unavailable". Review `docs/reviews/Q-93-flow.md`.
- Q-90/Q-91 merged 2026-11-10: D-176 (place/time words only for a false value, rule 6b other party, found guilty, director disqualification) + D-177 (no company filler, unclassed markers on choice fields only, noun runs need an involvement word). Review `docs/reviews/Q-90-declarations.md`. Q-92 F3/F5 spec notes done.
- Q-94 gate prep merged 2026-11-10: WP-A04 work-rights `country_bool` rows; D-180 an unknown place or region stops a work-rights label; D-181 Singapore rows never answer another country (names, all-caps, demonyms); Q-43 "Present" end; R3 F7 (D-178) / F11; Q-46 e pinned. Review `docs/reviews/Q-94-gate-prep.md`; follow-ups Q-95.
- Q-45 compose merged 2026-11-11: a required cover letter / "why us" field is written by the tailor's compose call from the master resume + JD, checked C1-C7 (D-183 sentence-start names too), filled and audited; `apply.compose.enabled` is **off** by default, so the field is captured as a question instead. Review `docs/reviews/Q-45-compose.md`; follow-ups Q-96 (card hint by note), Q-97 (LOWs, Edge fixture).

- Q-110 merged 2026-11-11 (session jobscraper-c6; 0b48371 + bundle 8f518e1): Inbox **Auto-apply** button + `routers/apply.py` (`GET /api/apply/status`, `POST /api/apply` with the AD §12.2 preflight). The owner's click is the only UI trigger (D-200); it runs the effective mode, live = `dry_run`. D-201 (the local model reads the whole profile under `apply.model_sees_sensitive`) is designed and reviewed (`q74_model_sees_sensitive.md` § D-201), build = Q-112, not started.

## Where we are
- M19 DONE. M20: the filler is complete through N6b; what remains is the M20 gate (D-83) plus follow-ups. Workday is filled in dry runs; account creation happens only inside owner-started attempts.
- Owner declarations are all false (D-87), plus `willing_to_sign_nda: true`, `government_employment: false`.

## Next 1–3 actions
1. M20 gate (D-83): owner-watched dry runs (start them from the Inbox Auto-apply button after an app restart), then 5 Greenhouse dry runs whose audits are read row by row. Needs the owner and Ollama; on the first one check Q-92 F4 (resume-name check on a real Workday review page) and Q-93 (the M1 delete count); Q-95 (a): a bare other-country citizenship question waits as a Private question. If a posting asks for a cover letter, try one dry run with `apply.compose.enabled: true` and read the composed text against the resume.
2. Entry-level `PageOutcome` channel (D-173) at the next contract version; Q-93 L2 residual; Q-95 (c) dead code; Q-96/Q-97.
3. Q-112 (D-201 build: engineer + tester pins F1/F2 + independent review, KA-2); Q-111 (`GET/PUT /api/apply/settings` with `writable` and `compose_enabled` for Q-100; tell jobscraper-72 the shapes).
4. Backlog: R3 F7/F11, Q-46 e, Q-45 compose_needed, Q-47, Q-43, Q-34, Q-32, Q-27, A04, Q-15.

## Watch out
- **The full suite skips the Edge tests silently** (a leaked asyncio loop; `edge_available()` caches the failure). Until the peer's Q-84 lands, gate every apply merge on separate `-k apply_e2e` and `-k apply_flow` runs.
- IDs: mine are Q-80..Q-83, Q-90..Q-93 (next Q-98) and D-150..D-189 (next D-186); the peer has Q-73..Q-79, Q-84..Q-89, D-100..D-119. Session jobscraper-c6 has Q-110..Q-119, D-200..D-209; Q-100's session has Q-100..Q-109, D-190..D-199. Re-read queue/status before taking one. Message the other live sessions (ListAgents) before merging into personal or building the bundle.
- Always run the full suite on the integration tree after merging personal: name collisions (Q-74 `_MONTHS`) show only at runtime.
- The engineer's scope hook refuses `tests/`: route test edits (even docstrings) to the tester.
- Before every push: deny-list scan, including req ids and employer names from real mail. Live app 8765; dev 8768/8769 with a DB copy.
- The scope guard blocks the Coordinator from writing `data/`; owner profile edits go via a surgical Python replace.
