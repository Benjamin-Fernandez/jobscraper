# Outbox: architect

Only `architect` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD architect → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

### 2026-11-08 architect → coordinator, software-engineer, tester (Q-83, D-171)
TYPE: handoff + blocker
RE: Q-83; review `docs/reviews/Q-82-declarations.md` MEDIUM-1..4 and §2; `docs/architecture/apply_design.md` §7.5 (after the D-170 block, before the D-90a bullet) and line 4; `src/jobscraper/apply/declarations.py`
BODY: **Blocker:** when I started writing, the main checkout's `apply_design.md` had no D-170 block (grep `D-170` = 0 hits), so I did not touch it, as the delegation said. **This entry is the amendment of record** until §7.5 carries it. Section A is the spec text to paste after the D-170 block (5-space indent, same as D-170), B is the line-4 changelog line, C is the code delta, D is the tester pins. D-171 is free (02_status §4 ends at D-169; D-170 comes with the Q-82 merge). Contracts unchanged, no ADR (private helpers; a refinement of D-170 under ADR-0003). Suggested commit: `docs(arch): Q-83 D-171 declaration details tail, places, applicant subject`.

**A. Spec text (§7.5, after the D-170 block)**

     - **D-171 (Q-83; review `docs/reviews/Q-82-declarations.md` MEDIUM 1–4): D-170 refined. No D-170 over-answer reopens.** Same helper, same notes, no new reason code. Owner intent D-87 (answer the standard declarations, never ask) weighed against ADR-0003 (fail closed).
       1. **Details tail (MEDIUM 2a).** D-164 step 1 becomes: drop a trailing answer hint; then, **only on a Yes/No DROPDOWN or RADIO** (`bool_shaped`), a trailing DETAILS TAIL; then a trailing answer hint again. DETAILS TAIL = `if yes` or `if so`, then optional please / kindly, then one VERB (provide, give, explain, specify, describe, elaborate, list, state), then 0–6 TAIL_OBJECT tokens (details, detail, further, more, full, brief, below, the, a, an, explanation, description, information, particulars, in, box, field, space, provided), running to the end of the label. Only the last `if yes` / `if so` is tried, and at least one token must stay before it. Any other tail ("If yes, please provide your position", "If so, when?") stays in and fails rule 1. On TEXT / TYPEAHEAD the tail is never dropped: that box asks for the details, so it ends `unknown`. `negated_question` and `_freedom_inverts` use the same strip. The tail has no negation in it, and the strip lets a mid-label "(Yes/No) If yes …" lose its hint too. Shape C sees the stripped tokens, so "Criminal record? If yes, please provide details." answers.
       2. **Vocabulary (MEDIUM 2b).** Every addition is class filler. None is a class phrase, because a phrase widens classification and D-171 changes only the frame test.
          - SHARED: + month, months (as year, years).
          - `conflict_audit_independence`: + aware (moved from SHARED, item 5).
          - `criminal_record`: + pleaded, plead (pleaded guilty), one ("… or pleaded guilty to one"), investigation (under investigation).
          - `bankruptcy`: + filed, personal (filed for personal bankruptcy), entered, into, individual, voluntary, arrangement, arrangements (an IVA is an insolvency procedure, the same class).
          - `regulatory_disciplinary`: + licence, license, licences, licenses ("suspended" is already a phrase, "revoked" already filler), disciplined.
          - `government_employment`: + current, former.
          - `non_compete`: + ability, work ("an agreement that restricts your ability to work for Acme"). "work" is not a PLACE_ANCHOR, so "… and work in Singapore" still fails.
          - **NARROWING** (`criminal_record`, 7): excluding, than, minor, traffic, violation, violations, unspent ("other" is already SHARED). These count only when the declaration value is **false** (taken before a D-91 inversion). A narrowed question keeps a true No. A Yes to "convicted, excluding minor traffic offences?" or "any unspent convictions?" may be false, so with a true value they are not covered and the field ends `unknown`.
          - Not added, recorded: "found guilty", "court order or injunction", "refused entry or deported", "dismissed or asked to resign", "disqualified as a director", "outstanding legal proceedings". These six labels are not declarations at all (classification, not D-170); they are a follow-up. Left unknown on purpose: "aware of any conflict of interest that may arise from your employment at Acme" (arguable), "crime involving dishonesty", "debarred by any government agency", "financial or business relationship … independence", "senior political figure" (each adds a second concept).
       3. **Places (MEDIUM 1).** singapore, country, countries, jurisdiction, jurisdictions, elsewhere, overseas and anywhere leave SHARED. They are covered only inside a PLACE QUALIFIER:
          - Form: one of in / within / of / from, then up to 2 of any / the / other / a / all, then a place noun (singapore, country, countries, jurisdiction, jurisdictions). Or a bare place adverb (elsewhere, overseas, anywhere).
          - Extension: repeated (or / and), optional preposition, up to 2 determiners, a place word ("in Singapore or any other country", "in Singapore or elsewhere").
          - Anchor: the qualifier counts only when the token right before it lies in a class-phrase span of a standing class, or is a PLACE_ANCHOR noun. PLACE_ANCHORS (56): crime(s), offences, offenses, felony, felonies, misdemeanor, misdemeanour, conviction(s), charge(s), charged, arrested, record(s), history, proceedings, case(s), court, order(s), petition(s), debt(s), action(s), sanction(s), sanctioned, investigation(s), body, bodies, authority, authorities, regulator(s), revoked, disciplined, licence, license, agreement(s), restriction(s), obligation(s), clause(s), contract(s), person(s).
          - Scope: only for a class set that holds a standing class, never for `disability` alone.
          - Result: a clause that names a place without a class ("… or currently in Singapore", "… or working in Singapore", "… a current role in Singapore", "… identify as living in Singapore") fails rule 1. The state words currently, now, still, status and subject stay SHARED: with places restricted and "aware" moved, no review probe passes through them.
       4. **Rule 3, the lead-in comes first (MEDIUM 1).** A piece with no class span and no status run passes only when no earlier piece has one: it is a lead-in ("Are you, or have you ever been, …"). A trailing all-filler piece ("I am not a PEP and I am aware of the status", "… and I am in Singapore") fails, on a dropdown and on a checkbox alike.
       5. **"aware" (MEDIUM 3).** Moves from SHARED to `conflict_audit_independence` filler. A conflict of interest is something the applicant knows of (D-90a keeps "Are you aware of any conflict of interest?" → No). For any other class, "aware of" asks what the applicant knows about other people ("Are you aware of any criminal convictions against Acme?"). "against" stays SHARED; with "aware" moved, the review's against-rows fail.
       6. **New rule 6, the applicant is the subject (MEDIUM 3).** At the start of `toks`, and right after each rule-3 cut, a status starter must be followed by `you` or `your`. These fail: "Are other people politically exposed persons?", "Is the person politically exposed?", "Is there a criminal record?", "Are you or is any other person a PEP?". "Has your professional licence ever been revoked?" passes. Relatives are exempt by design: D-170 does not run on the employer classes, so "Do any of your relatives work at Acme?" keeps D-164. The D-164 statement runs "there is" / "there are" stay, because the checkbox attestation "there is no …" uses them.
       7. **MEDIUM 4: kept recorded, not closed.** The employer-class compound ("Do you hold shares in this company and a valid visa?" → No; a single checkbox "I hold no shares in this company and have a valid visa" is ticked) stays the recorded D-170 residual. Why:
          - Those five classes answer only when the label names this employer (gate 4), and they answer from computed facts.
          - Closing it needs five new closed vocabularies with no label corpus behind them (the review replayed no employer-class variety). That trades one recorded shape for unmeasured under-answers on the commonest employer questions (relatives, previously applied).
          - D-83 reads every dry-run row before any real submit.
          - Revisit trigger: one such label in a dry-run audit or a live attempt. Then run rules 1, 3 and 6 on the employer classes with their own filler (queue it then).
       - Rejected:
         - (a) Strip any `if …` tail. It reopens "… ? If yes, are you also …".
         - (b) Pleaded guilty and IVA as class phrases. They widen classification beyond the frame fix.
         - (c) Cut before every and / or (the review's stronger rule 3). It breaks "suspended or revoked" and "adjudged bankrupt or entered into an IVA" without closing anything that items 3–6 leave open.
         - (d) Narrowing words for every value. A true value would give a Yes that may be false.
       - Vocabulary after D-171: SHARED 65 (72 − 8 places − aware + month, months); per class 169 (pep 10, conflict 12, criminal_record 29, bankruptcy 21, regulatory 25, non_compete 49, government 14, disability 9); NARROWING 7; PLACE_ANCHORS 56. Adding a word changes the spec and needs a pin.
       - Oracles D-171: table D below (Yes/No dropdown unless stated; employer Acme; sample profile, every declaration false; `disability_status: no` where stated). Every D-164, D-169b and D-170 row keeps its result.

**B. Line-4 changelog line (append after the D-170 delta)**
`**D-171 delta (Q-83, 2026-11-08): §7.5 D-170 refined: a trailing "if yes/so, please provide details" tail is dropped on Yes/No choices, class filler for the common real suffixes (narrowing words only for a false value), place words only as a qualifier after a class noun, the lead-in piece only first, "aware" for conflict of interest only, the applicant as the subject; employer-class compound kept recorded; Q-82 review MEDIUM 1–3 closed; contracts unchanged.**`

**C. Code delta (`src/jobscraper/apply/declarations.py` only; one lane)**
1. Constants (next to `_STATUS_FILLER`):
   - `_STATUS_FILLER`: delete `country countries jurisdiction jurisdictions singapore elsewhere overseas anywhere aware`; add `month months` (65 words).
   - `_CLASS_FILLER`: CONFLICT `+ aware`; CRIMINAL_RECORD `+ pleaded plead one investigation`; BANKRUPTCY `+ filed personal entered into individual voluntary arrangement arrangements`; REGULATORY `+ licence license licences licenses disciplined`; NON_COMPETE `+ ability work`; GOVERNMENT_EMPLOYMENT `+ current former`.
   - New: `_NARROWING_FILLER = {L.CRIMINAL_RECORD: frozenset("excluding than minor traffic violation violations unspent".split())}`
   - New: `_PLACE_NOUNS = frozenset("singapore country countries jurisdiction jurisdictions".split())`, `_PLACE_ADVERBS = frozenset({"elsewhere", "overseas", "anywhere"})`, `_PLACE_PREPS = frozenset({"in", "within", "of", "from"})`, `_PLACE_DETS = frozenset({"any", "the", "other", "a", "all"})`, `_PLACE_ANCHORS = frozenset("""crime crimes offences offenses felony felonies misdemeanor misdemeanour conviction convictions charge charges charged arrested record records history proceedings case cases court order orders petition petitions debt debts action actions sanction sanctions sanctioned investigation investigations body bodies authority authorities regulator regulators revoked disciplined licence license agreement agreements restriction restrictions obligation obligations clause clauses contract contracts person persons""".split())` (56).
   - New: `_APPLICANT_SUBJECT = frozenset({"you", "your"})`.
   - New: `_DETAIL_IFS = (("if", "yes"), ("if", "so"))`, `_DETAIL_VERBS = frozenset("provide give explain specify describe elaborate list state".split())`, `_DETAIL_OBJECT = frozenset("details detail further more full brief below the a an explanation description information particulars in box field space provided".split())`, `_DETAIL_OBJECT_MAX = 6`.
2. New helpers (after `_strip_answer_hint`):
```python
def _strip_detail_tail(toks):
    """D-171 (1): drop a trailing "if yes/so, [please] provide details ..." tail (closed)."""
    for i in range(len(toks) - 3, 0, -1):
        if tuple(toks[i:i + 2]) in _DETAIL_IFS:
            rest = toks[i + 2:]
            if rest[:1] in (["please"], ["kindly"]):
                rest = rest[1:]
            ok = bool(rest) and rest[0] in _DETAIL_VERBS and len(rest) - 1 <= _DETAIL_OBJECT_MAX \
                and all(t in _DETAIL_OBJECT for t in rest[1:])
            return toks[:i] if ok else toks          # only the last "if yes/so" is tried
    return toks


def _strip_trailers(toks, tail):
    toks = _strip_answer_hint(toks)
    return _strip_answer_hint(_strip_detail_tail(toks)) if tail else toks
```
   Place helpers (before `_one_status_question`):
```python
def _place_end(toks, i, prep_required):
    if i < len(toks) and toks[i] in _PLACE_ADVERBS:
        return i + 1
    j = i
    if j < len(toks) and toks[j] in _PLACE_PREPS:
        j += 1
    elif prep_required:
        return None
    for _ in range(2):
        if j < len(toks) and toks[j] in _PLACE_DETS:
            j += 1
    return j + 1 if j < len(toks) and toks[j] in _PLACE_NOUNS | _PLACE_ADVERBS else None


def _place_spans(toks, classes, standing_cover):
    """D-171 (3): place qualifiers right after a standing class phrase or a PLACE_ANCHOR."""
    if not set(classes) & STANDING_DECLARATIONS:
        return []
    out = []
    for i in range(1, len(toks)):
        if (i - 1) not in standing_cover and toks[i - 1] not in _PLACE_ANCHORS:
            continue
        end = _place_end(toks, i, True)
        if end is None:
            continue
        while end < len(toks) and toks[end] in ("or", "and"):
            nxt = _place_end(toks, end + 1, False)
            if nxt is None:
                break
            end = nxt
        out.append((i, end))
    return out
```
3. `_one_status_question(toks, classes, employer_names=(), extra_runs=(), narrowing_ok=False)`:
   - After `anchors`: `standing_cover = {i for c in classes & STANDING_DECLARATIONS for a, b in _class_spans(toks, c) for i in range(a, b)}`; add `+ _place_spans(toks, classes, standing_cover)` to the `covered` span list.
   - After `filler`: `if narrowing_ok: filler = filler.union(*(_NARROWING_FILLER.get(c, frozenset()) for c in classes))`.
   - Replace the rule-3 `return all(...)` with:
```python
    for s in [0, *(k + 1 for k in cuts)]:                        # rule 6 (D-171): the applicant
        if toks[s] in _STATUS_STARTERS and (s + 1 >= len(toks) or toks[s + 1] not in _APPLICANT_SUBJECT):
            return False
    seen = False
    for a, b in zip(bounds, bounds[1:]):                         # rule 3; D-171: a lead-in only first
        if any(a <= s < b for s, _e in anchors):
            seen = True
        elif seen or not all(t in _STATUS_FILLER for t in toks[a:b]):
            return False
    return True
```
   (`toks` is non-empty here: rule 2 needs a class span.)
4. `question_frame(label_toks, classes, f, employer_names=(), narrowing_ok=False)`: `from .resolve import bool_shaped`; `yes_no = f.fit_type in (FieldType.DROPDOWN, FieldType.RADIO) and bool_shaped(f)`; first line becomes `toks = _strip_frame_prefix(_strip_trailers(list(label_toks), yes_no))`; pass `narrowing_ok=narrowing_ok` to `_one_status_question`.
5. `negated_question` and `_freedom_inverts`: replace the inline ANSWER_HINTS loop with `toks = _strip_trailers(toks, True)`.
6. `_bool_answer`: right after the `value is None` return, `narrowing_ok = value is False` (before any `value = not value`); pass `narrowing_ok=narrowing_ok` to the checkbox `_one_status_question` call (rule 5) and to `question_frame`.
7. Update the D-170 comment block above `_STATUS_FILLER` to cite D-171. No other module changes; `locks` reaches all this through `answer()`.
8. `tests/test_apply_declarations_d170.py`, `test_d170_rule3_a_piece_without_a_class_or_status_run_fails_even_with_listed_words`: change only the docstring, to "The second clause holds no class span and no status run, and after D-171 'Singapore' is not filler either, so rules 1 and 3 both refuse it." The assertion stays; it still passes.
Verify: `python tests/run_tests.py -k declarations`, `-k apply_contracts`, `-k llm_fill`, `-k layering`, then the full suite.

**D. Tester pins (new file `tests/test_apply_declarations_d171.py`, gated on `declarations:_place_spans`, same `_run` helper as the d170 file)** (59 rows)
| # | Label | Want |
|---|---|---|
| 1 | Have you ever been convicted of a crime? If yes, please provide details. | No (tail) |
| 2 | Do you have a criminal record? If yes, please provide details. | No |
| 3 | Have you ever been convicted of a felony? If yes, please explain | No |
| 4 | Are you currently bound by a non-compete agreement? If yes, please specify. | No |
| 5 | Have you ever been declared bankrupt? If so, please give details. | No |
| 6 | Have you ever been convicted of a criminal offence or declared bankrupt? If yes, please provide details below. | No (agreement + tail) |
| 7 | Criminal record? If yes, please provide details. | No (shape C after the strip) |
| 8 | Have you ever been convicted of, or pleaded guilty to, any criminal offence? | No |
| 9 | Have you ever been convicted of a criminal offence or pleaded guilty to one? | No |
| 10 | Have you ever been convicted of a crime (excluding minor traffic offences)? | No (narrowing, false value) |
| 11 | Have you ever been convicted of a criminal offence (other than a minor traffic violation)? | No |
| 12 | Have you ever been convicted of a criminal offence, other than a minor traffic offence? | No |
| 13 | Have you ever been convicted of a criminal offence in the last 12 months? | No |
| 14 | Are you, or have you been in the last 12 months, a politically exposed person? | No |
| 15 | Are you a current or former government official? | No |
| 16 | Have you ever filed for bankruptcy? · Have you ever filed for personal bankruptcy? | No · No |
| 17 | Have you ever been adjudged bankrupt or entered into an individual voluntary arrangement? | No |
| 18 | Do you have any unspent criminal convictions? | No |
| 19 | Are you currently under investigation for any criminal offence? | No |
| 20 | Has your professional licence ever been revoked or suspended? | No (subject "your") |
| 21 | Have you ever had a professional licence suspended or revoked? | No |
| 22 | Have you ever been disciplined by any professional regulatory body? | No |
| 23 | Are you party to any agreement that restricts your ability to work for Acme? | No |
| 24 | Have you been convicted of a criminal offence in Singapore or any other country? | No (place after a class noun) |
| 25 | Have you ever been declared bankrupt in any jurisdiction? | No |
| 26 | Are you a politically exposed person in Singapore or elsewhere? | No (anchor "person") |
| 27 | row 1 as TEXT | unknown (tail kept on TEXT) |
| 28 | Are you a PEP? If yes, please provide your position. | unknown (tail object closed) |
| 29 | Have you ever been declared bankrupt? If so, when? | unknown (no tail verb) |
| 30 | rows 10 and 18 with `criminal_record: true` | unknown · unknown (narrowing only for false) |
| 31 | Have you ever been convicted of a crime? with `criminal_record: true` | Yes (control) |
| 32 | Are you a politically exposed person or currently in Singapore? | unknown |
| 33 | Are you a politically exposed person or currently overseas? | unknown |
| 34 | Have you been convicted of a crime or been in Singapore for the past year? | unknown |
| 35 | Do you have a criminal record or any status in Singapore? | unknown |
| 36 | Are you bound by a non-compete or working in Singapore? | unknown |
| 37 | Do you have a non-compete agreement or a current role in Singapore? | unknown |
| 38 | Are you a government employee or currently working in Singapore? | unknown |
| 39 | Have you worked for the government or worked in Singapore? | unknown |
| 40 | Do you have a disability or identify as living in Singapore? (`disability_status: no`) | unknown |
| 41 | checkbox "I confirm I am not a PEP and am currently in Singapore" | not ticked, unknown |
| 42 | checkbox "I am not a PEP and I am aware of the status" | not ticked, unknown |
| 43 | checkbox "I have no criminal record and I am in Singapore" | not ticked, unknown |
| 44 | checkbox "I am not bound by a non-compete and I am currently in Singapore" | not ticked, unknown |
| 45 | checkbox "I am not subject to any non-compete or working in Singapore" | not ticked, unknown |
| 46 | Are other people politically exposed persons? · Are any people politically exposed persons? | unknown · unknown |
| 47 | Is the person politically exposed? | unknown |
| 48 | Are you aware of any politically exposed persons? | unknown |
| 49 | Are you aware of any criminal convictions against Acme? · …any bankruptcy proceedings against Acme? · …of the criminal record status of Acme? | unknown ×3 |
| 50 | Is there a criminal record? | unknown |
| 51 | Are you or is any other person a PEP? | unknown (rule 6 after the cut) |
| 52 | Do any of your relatives work at Acme? | No (relatives: D-170/171 do not run) |
| 53 | Are you aware of any conflict of interest with Acme? · Are you aware of any conflict of interest? | No · No ("aware" is conflict filler) |
| 54 | Are you a senior political figure? · Are you aware of any conflict of interest that may arise from your employment at Acme? | unknown · unknown (left on purpose) |
| 55 | checkbox "I confirm I am not bound by any restrictive agreement" | ticked (rule 5 control) |
| 56 | Are you, or have you ever been, a senior government official? | No (lead-in first) |
| 57 | Q-48 `F1_LABEL` (optional) | No, rule_id `conflict_audit_independence+non_compete` |
| 58 | guard: `test_apply_declarations_d170.GUARD_ROWS` and every d170 / d164 / Q-48 / D-89 / D-90a / D-91 pin | unchanged (whole `-k declarations` green) |
| 59 | guard: `Are you subject to a non-compete and are you in Singapore?` | unknown (now also by item 3) |
(The d170 docstring note moved to part C item 8, for the engineer.) Update 2026-11-08: A and B are pasted into the eng-Q83 worktree's `apply_design.md` (branch eng/Q-83-declarations), with a condensed oracle table; the blocker above is resolved.
Open questions: none for the owner. Follow-up for the queue: classify the six non-declaration labels (item 2, "Not added").
STATUS: open

### 2026-11-07 architect → coordinator, software-engineer, tester (Q-81 → Q-80 addition)
TYPE: handoff
RE: Q-81 (closes it), Q-80; review `docs/reviews/Q-48-and-lane-M-fixes.md` re-review F11, F12, F13, F15, F16; `docs/architecture/apply_design.md` line 4 (delta), §5.4 template line 379, §7.5 (gate 2 D-164 block, D-91 bullet, D-166 bullet, gate 4 D-165 note, D-165 bullet)
BODY: §7.5 now records the decisions below; contracts are unchanged (CONTRACT_VERSION stays). Please record D-164..D-166 in 02_status §4, mark Q-81 DONE, and commit (I have no shell). Suggested message: `docs(arch): Q-81 D-164..D-166 declaration frame shapes, NDA unset, compound consent`.
- D-164 (F13 + F12): the STATUS frame is a closed list of label shapes. Answering is extended to prefixed, indirect and short noun-phrase labels; frame runs "anywhere in the label" are not accepted.
- D-165 (F15, F16): `willing_to_sign_nda` unset = no answer (§5.4 template line now `null`). Consent verbs follow D-90a (comfortable / happy to / open to → unknown; sign / signing alone is not consent). F15 (a) and (b) are kept as built, each with a reason. No code change.
- D-166 (F11): the `_NDA_LABEL_VOCAB` closed-vocabulary rule is now spec. Already built, no code change. Tester: confirm the F11 pins in `tests/test_apply_declarations_review.py` (~line 85) cover the four oracles listed in §7.5, including "Would you sign an NDA if asked?" → Yes.
CODE DELTA (add to Q-80; one lane, `src/jobscraper/apply/declarations.py` only; tester pins = the D-164 oracle table in §7.5):
1. Replace `_status_frame(toks)` with `question_frame(label_toks, classes, f)`, steps 1-3 of D-164:
   - PREFIX strip: please, kindly, declaration, declarations, self declaration, note, question, important; at most 3 tokens; after the trailing ANSWER_HINTS strip.
   - Optional LEAD: confirm, indicate, state, specify, advise, tell us, let us know; then optional if / whether / that.
   - Shape A: today's starters and `_STATUS_RUNS`, plus the leading runs i am, i have, i hold, there is, there are.
   - Shape B: only after a LEAD: you are, you're, you have, you've, you were, you had, you hold, you do, you did.
   - Shape C: DROPDOWN/RADIO and `resolve.bool_shaped`; classes ⊆ NOUN_CLASSES; ≤ 6 tokens left; each token in a matched phrase span or NOUN_FILLER; no NDA object span.
2. `_bool_answer` (non-checkbox branch): call the frame for every class except NDA_WILLINGNESS, including after `_freedom_inverts` succeeds (F12; today `:836-839` skips it). Pass the class set: `{cls}`, or the agreed classes from `answer()` (today `cls=None` on the agreement path, so it needs a new argument).
3. Gate 1 `_starts_as_question`: use the same PREFIX strip (today only please / kindly). No LEAD, no shape C.
4. Behaviour changes to pin: "Free from any restrictive covenants?" Yes → unknown. "Politically exposed person (PEP)?", "Criminal record", "Bankruptcy", "Disability" (Yes/No), "Declaration: Are you a politically exposed person?", "Note: Do you have a non-compete?", "Please confirm: Are you a PEP?", "Please indicate if you have ever been bankrupt": unknown → No. Unchanged (stay unknown): "Non-compete agreement?", "Confidentiality agreement", "Criminal record check", "Former employee?", any noun phrase on TEXT or a single checkbox. Unchanged (still Yes): "Confirm you are free from any restrictive covenants".
   No existing test asserts the old unknowns (grep for "not a status question" in tests/ finds nothing). Run `-k declarations`, `-k apply_contracts`, `-k llm_fill`, `-k layering`, then the full suite.
Open questions: none for the owner. Note: F14 (dead `locks.NEGATIONS`) stays in Q-80 as queued.
STATUS: open

### 2026-11-02 architect → coordinator, engineer, tester (Q-48, D-87)
TYPE: handoff
RE: Q-48, D-87 (extends D-55), KA-2; AD §5.4, §7.5; LF §4 L3/L5/L7; QD §3 rows 4 and 14; contracts v5 (additive)
BODY: Fast-track amendment to tier 4 (declarations). Budget ran out (36/35 calls) before the doc fold-in: **this entry is the amendment of record** until AD §7.5, LF §4, QD §3 and `contracts.py` carry it (about 5 edits, no new design). No S values below; labels are employer text.

**A. Decisions**
- A1 Keep the key `declarations.non_compete`, widened to "any agreement that limits the work you can do". Same fact, same owner answer; a rename changes a `DeclarationLabel` value (breaking, ADR) and needs a D-79 migration for no behaviour gain. Only the form label and the example comment change.
- A2 New standing class and key `government_employment` (bool, default false).
- A3 Disability: no new key. `us_self_id.disability_status` is the disability answer for every country (one value, nothing to drift). A new tier-4 class `disability` (label-only match) reads it: S, filled by the program, `sensitive=True`, locked before the model (L3; G7 already lists disability).
- A4 Agreement rule: when a label matches 2+ classes, all of them **standing** (`pep`, `conflict_audit_independence`, `criminal_record`, `bankruptcy`, `regulatory_disciplinary`, `non_compete`, `government_employment`) and all truth values equal → that value. A set holding an employer-specific class, `health` or `disability` stays AMBIGUOUS: D-70's prefill overwrite and L6's skip key off one employer-specific class, so they stay untouched.
- A5 Checkboxes: the agreement rule does **not** apply to a single CHECKBOX; a multi-class box stays AMBIGUOUS (required → unknown `attestation_unclear`, optional → blank). ADR-0003: a tick is a signed statement, and token rules can't tell the polarity of each class ("I have no conflict of interest and am bound by a non-compete" has one negation and mixed polarity). Single-class boxes keep today's rule; with the new phrases "I confirm I am not bound by any restrictive agreement" is single-class `non_compete` → ticked.
- A6 L7 stays (negated Yes/No → unknown) with two changes: (a) NS-exclusion runs ("not including national service") are removed before the negation test (L7 and `is_negated`); (b) `declarations.answer()` applies L7 itself on non-checkbox fields, so the Greenhouse resolver path fails closed too (the wider tier 4 would otherwise map "Are you free of any non-compete?" → `fit_bool(False)` → "No").
- A7 R1 longest match: a class's hit is dropped when every span it matched lies inside a longer matched span of another class. This changes nothing in today's table (no cross-class nesting). It lets "worked for the government" beat prior_employment's "worked for", "employed by the government" beat "employed by", and pep's "senior government official" beat "government official".
- A8 D-79: for `declarations.<bool>` paths only, `nil`, `none`, `na`, `n_a`, `not_applicable` (key form) read as false. `us_self_id.disability_status`: `none`, `nil`, `no_disability`, `not_disabled` → `no`.

**B. Classifier (AD §7.5)**
- B1 `non_compete` phrases (replace the row): non compete, non competes, noncompete, non competition, non solicitation, non solicit, nonsolicitation, non disclosure, nondisclosure, nda, ndas, confidentiality agreement, confidentiality agreements, confidentiality obligation, confidentiality obligations, restrictive covenant, restrictive covenants, restrictive agreement, restrictive agreements, restraint of trade, garden leave, bound by any agreement, agreement that restricts, agreements that restrict, agreement that would restrict, agreement restricting, agreements restricting, agreement that prevents, agreement that would prevent, agreement that prohibits, agreement that would prohibit, stock option agreement, stock option agreements, stock option or restricted stock, restricted stock grant, restricted stock agreement, restricted stock unit agreement, stock grant agreement, equity grant agreement. ("subject to any restrictions" is left out on purpose: work-rights questions use it.)
- B2 `government_employment` phrases: civil service, civil servant, civil servants, public service, public servant, public sector, public officer, government service, government employee, government employees, government employment, government agency, government agencies, government ministry, government department, government body, government bodies, statutory board, statutory boards, government official, public official, worked for the government, worked for government, worked for a government, worked for any government, worked in the government, worked in government, work for the government, working for the government, employed by the government, employed by government, employed by a government, employed by any government, employed in the government, employed in government, have you worked in government, have you worked in the government, have you worked in the public sector, have you worked in the public service, have you worked in the civil service.
  - MILITARY terms (used by the rule below; not class phrases): military, armed forces, armed services, defence force, defence forces, defense force, army, navy, air force, national service, ns, nsf, nsman, saf, conscription, uniformed service, uniformed services.
  - NS exclusion: an exclusion run (excluding, exclude, excludes, except, other than, apart from, aside from, besides, save for, not including, not counting, does not include, do not include) with an NS term starting within the next 4 tokens, or an NS term followed within 3 tokens by not included / excluded / not counted / does not count. NS terms: national service, full time national service, ns, nsf, mandatory military service, compulsory military service, mandatory national service, military service, mandatory service, compulsory service, conscription.
  - UNSURE phrases: government linked, glc, glcs, government owned, state owned, state enterprise.
  - Rule (gov = a B2 hit after R1; mil = a MILITARY hit; excl = NS exclusion; unsure = an UNSURE hit): (gov or mil) and excl and not unsure → `government_employment`. Gov and not mil and not unsure → `government_employment` (the owner reads "worked for the government" as not counting NS). Gov with (mil and no excl) or with unsure → **AMBIGUOUS** (unknown, never No). Mil, no excl, no gov → no `government_employment`: an NS-inclusive question belongs to L5 / `ns_status`, and tier 4 doesn't answer it unless another class matches.
  - Against `pep`: R1 makes "senior government official" pep only; "public office" stays pep. "Held public office or worked in the civil service?" → {pep, government_employment} → A4 → No; if the profile's two values differ → AMBIGUOUS (a real disagreement).
- B3 `disability` (matched on the **label only**: EEO preambles in descriptions mention disability): disability, disabilities, disabled, person with disability, persons with disabilities, people with disabilities, pwd, pwds, handicap, handicapped. A label that also says veteran, gender, race, ethnic, ethnicity, religion or marital → AMBIGUOUS.
- B4 `classify_all(label_norm, description_norm="") -> tuple[frozenset[DeclarationLabel], bool]` (classes, unsure): phrase hits → R1 → D-69 pair → B2 rule. `classify()` is built on it: unsure → AMBIGUOUS; 1 class → it; 2+ → AMBIGUOUS; 0 → attestation marker → AMBIGUOUS, else None (unchanged contract for callers).

**C. Rules (AD §7.5)**
- `government_employment`: `declarations.government_employment` (default false); joins `_PLAIN_BOOLS`.
- `disability`: `no` → False, `yes` → True, `decline`/absent → None. A bool on a bool-shaped field → `fit_bool`; another choice → `fit_enum` with `DISABILITY_VALUE_MAP` = the EEO disability entry plus "no": no disability, i do not have a disability, i don't have a disability, i do not have any disability, not a person with disability, i am not a person with disability; "yes": i am a person with disability, person with disability. A single checkbox uses today's negation rule. None → the decline option when offered; else required → unknown, optional → blank (notes "disability: declined, no decline option" / "no offered option fits the declaration").
- Agreement (inside `answer()` when label is AMBIGUOUS): `classes, unsure = classify_all(norm_label(f.label), norm_label(f.description))`; when not unsure, 2+ classes, all in `STANDING_DECLARATIONS`, `f.type` not CHECKBOX and all `truth()` equal → `fit_bool` of that value; `rule_id` and the source suffix = the sorted class values joined by `+` (e.g. `conflict_audit_independence+non_compete`), note `agreed: <classes>`, `sensitive=True`, 0.95. Otherwise unchanged (`attestation not recognised`).
- L7 in `answer()` (A6b): a non-checkbox field whose label is negated (not, never, no, none, neither, free of, without; NS-exclusion runs removed first) → `_ended`, note "negated declaration question".
- `health`: unchanged.

**D. Profile schema**
- `config/applicant.example.yaml`: `disability_status: decline  # no | yes | decline. Answers every disability question, in any country (D-87)`; `non_compete: false  # any agreement that limits the work you can do: non-compete, non-solicitation, NDA or confidentiality, stock option or restricted stock terms`; new `government_employment: false  # ever worked for the government, public sector, a statutory board or the military, not counting National Service` (after `non_compete`).
- `applicant.py`: `BOOLS += "declarations.government_employment"`; A8 synonyms. Form rows (QD §3 rows 4 and 14 follow):
  - `_I("declarations.non_compete", "Are you bound by any agreement that limits the work you can do, such as a non-compete, non-solicitation, NDA or stock grant terms?", "bool")`
  - `_I("declarations.government_employment", "Have you ever worked for the government, public sector or military, not counting National Service?", "bool", help="Questions that include National Service use your National Service status instead.")` (after non_compete)
  - `_I("us_self_id.disability_status", "Disability status", "enum", _enum_opts("us_self_id.disability_status"), help="Used for every disability question, in any country, not only US forms.")`

**E. Engineer WP-Q48 (one lane; `apply/declarations.py`, `applicant.py`, `config/applicant.example.yaml`)**
- E1 (architect, with the doc fold-in): `DeclarationLabel.GOVERNMENT_EMPLOYMENT = "government_employment"`, `DeclarationLabel.DISABILITY = "disability"`; v5 additive; not in `EMPLOYER_SPECIFIC_DECLARATIONS`.
- E2 `declarations.py`: B1–B4, R1, `STANDING_DECLARATIONS`, C rules, L7 in `answer()`, NS-exclusion strip in `is_negated`.
- E3 `applicant.py`: BOOLS, A8, the D form rows. E4 the example yaml lines.
- E5 At lane M's merge (`locks.py`): L3 must pass AMBIGUOUS to `declarations.answer()` rather than end it itself, and L7 must use the declarations negation helper. One check, no new code if it already delegates.
- Verify: `python tests/run_tests.py -k declarations`, `-k applicant`, then the full suite.

**F. Tester oracles (employer "Acme"; the example profile defaults, plus a fixture `disability_status: no`)**
- F1 Optional Yes/No: "Have you signed or accepted any agreement, or are you otherwise subject to any restrictions, that 1) will restrict the job responsibilities you may perform or 2) prohibit you from working for Acme, e.g. non-competition agreement, non-disclosure agreement, non-solicitation agreement, stock option or restricted stock grant agreement with your current or former employers or pursuant to applicable government conflict of interest restrictions?" → `classify` AMBIGUOUS; `classify_all` ({non_compete, conflict_audit_independence}, False); `answer` FILLED "No", tier DECLARATION, rule_id `conflict_audit_independence+non_compete`, sensitive.
- F2 F1 with `conflict_audit_independence: true` → optional blank_optional; required → unknown (LF reason `attestation_unclear`).
- F3 "Have you ever worked for the Government (excluding mandatory military service)?" → `government_employment` (prior_employment dropped by R1) → "No".
- F4 "Have you ever worked for the government, not including National Service?" → `government_employment`, L7 doesn't fire → "No".
- F5 "Have you served in the armed forces?" → `classify` None (not this lock).
- F6 "Have you ever been employed by the government or served in the military?" → AMBIGUOUS → required unknown.
- F7 "Have you ever worked for a government-linked company?" → AMBIGUOUS.
- F8 "Are you, or have you ever been, a senior government official?" → pep only → "No"; still pep-only with `government_employment: true`.
- F9 "Have you held public office or worked in the civil service?" → "No" (agreement); with `pep: true` → AMBIGUOUS.
- F10 "Are you a person with disability (PWD)?" Yes/No → "No"; with `decline` and a "Prefer not to say" option → that option; `decline`, no decline option: required → unknown, optional → blank.
- F11 Label "Disability status", options "Yes, I have a disability (or previously had a disability)" / "No, I do not have a disability and have not had one in the past" / "I do not want to answer" → the "No, I do not have…" option.
- F12 Label "Gender" with a description that mentions disability → not `disability`.
- F13 "Do you have any disability or medical condition that may affect your work?" → AMBIGUOUS → optional blank / required unknown.
- F14 "Do you have any medical condition we should know about?" required with a decline option → the decline option; optional → blank (health unchanged).
- F15 Required single checkbox "I confirm I am not bound by any restrictive agreement" → ticked ("true").
- F16 Required single checkbox "I confirm I have no conflict of interest and am not bound by any non-compete" → unknown (A5).
- F17 "Are you free of any non-compete agreement?" Yes/No → unknown (L7, resolver path too).
- F18 "Have you previously worked for us or any government agency?" → AMBIGUOUS (employer-specific in the set).
- F19 Regression: every pre-D-87 classify oracle unchanged (R1 changes nothing on the old table).
- F20 normalise: `government_employment: "NA"` / `"nil"` → false; key missing → false; `disability_status: "none"` → "no".

**G. Open (coordinator)**
- G1 Recommend adding `military`, `armed forces` to G7 `SENSITIVE_LABEL` (lane M `guards.py`, one constant). Without it, an NS-inclusive question that no NS `yes_if` rule matches (F5) can still reach the model.
- G2 No NS `yes_if` rule for "served in the armed forces": it isn't true for every enum value (NS can be served in the police or civil defence), so it stays captured.
- WRITTEN INTO DOCS (2026-11-02, follow-up): AD §5.4 + §7.5, LF §4 L3/L7 + G7 (D-88) + G2(d) (restated-fact rule: accepted, the written option stays the program's fit), QD §3 rows 4 and 14, `contracts.py` (2 additive `DeclarationLabel` members, v5). WP-Q48 and the tester WP are ready to build.
- D-89 (2026-11-02): R1 extended in AD §7.5: a prior/current-employee span that overlaps a government span also loses. The drop is skipped when the label names this employer (`us`/`our`, or `employer_names` via `company_match`). F18 stays AMBIGUOUS; NS-inclusive military questions are unchanged. New oracles: "Have you previously worked for the government?" and "Are you currently employed by a government body?" → `government_employment` → No.
- D-90 (2026-11-02): written into AD §7.5: phrase-table rows for disability and prior/current employment conditioned; the "Negated question" rule is replaced by five gates (field type, status frame, polarity with a grown NEGATIONS list and the negative-attestation checkbox rule, the employer condition shared with Q-46c, disability status frames), plus no S state in notes. Also the "Value onto the field" checkbox clause, and LF §4 L3/L7 (one shared helper, F10). Open: an extension to the WILLINGNESS list, proposed and marked pending in AD (see the report).
- D-91 (2026-11-02): written into AD §7.5. Gate 3: freedom forms (free from/of, clear of/from, unrestricted by, unencumbered by, not bound/subject/party to) take the inverted value when they are the only negation and govern every class phrase. Gate 2: new class `nda_willingness` (an NDA object plus a consent verb) reads the new `declarations.willing_to_sign_nda` (default false; not standing). Also AD §5.4 yaml, the QD §3 row-14 Profile row, and `DeclarationLabel.NDA_WILLINGNESS` (v5 additive). Engineer: classifier + truth + form row + example yaml line. Tester: "Are you free from any restrictive covenants?" → Yes; "Are you willing to sign an NDA?" → the switch; "I agree to sign the NDA" box ticked only when true; "Are you willing to sign a non-compete?" → unknown; "Are you not free from …" / two negations → unknown.
### 2026-11-07 architect → coordinator, software-engineer, tester (Q-35 N6a defect D1, D-167)
TYPE: handoff
RE: tester D1 (`comms/outbox/tester.md` "Q-35 WP-N6a oracles settled"); `tests/test_apply_n6a_defect_pins.py::test_d1_*`; `src/jobscraper/apply/contracts.py` (FormField.fit_type); `docs/architecture/llm_fill_design.md` §3.1 row "Fit type", §15 D-167, header
BODY: Decision D-167: a TYPEAHEAD that has an offered list (non-empty `options`) is fitted as a DROPDOWN. A search typeahead (`options == ()`) stays free text.
Contract (done; v5, additive, no CONTRACT_VERSION bump):
- New derived property `FormField.fit_type -> FieldType`. It returns DROPDOWN when `type is TYPEAHEAD and options`, else `type`.
- `CHOICE_TYPES` is unchanged.
Rejected options:
- (a) Adding TYPEAHEAD to `CHOICE_TYPES`. This would break search typeaheads: `fit_text`, `fit_country` and `fit_bool` would return None when there are no options.
- (b) The predicate repeated at each site. About 20 sites would drift apart.

Engineer delta. Replace `f.type` with `f.fit_type` at exactly these lines. Leave the other `f.type` reads alone.
- resolve.py
  - L376 `bool_shaped`: `if f.fit_type not in SINGLE_CHOICE or not f.options:`
  - L493 `fit_bool`: `if f.fit_type in CHOICE_TYPES:`. L497 stays as it is: it now sees only unlisted typeaheads.
  - L518 `fit_decline` and L589 `fit_enum`: `f.fit_type not in CHOICE_TYPES`
  - L606 `fit_text`: `if f.fit_type in CHOICE_TYPES:`. L609 stays as it is.
  - L649 `fit_number`: `if f.fit_type in SINGLE_CHOICE:`
  - L721 `fit_country`: `if f.fit_type in CHOICE_TYPES:`
  - L819 (PHONE_COUNTRY_CODE) and L839 (COUNTRY): `f.fit_type in CHOICE_TYPES`. L876 (HOW_HEARD) is already equivalent; optionally write it as `f.fit_type in CHOICE_TYPES`.
  - L1017 `_extra_fit` choice: `if f.fit_type not in SINGLE_CHOICE:`
  - L1146 and L1152 memory tier: `f.fit_type`. Keep L1134's memory key `f.type.value` (stored rows stay valid).
  - L1204 `_llm_kind`: leave it. Tier 5 is retired, and the rules path gets DROPDOWN from the schema.
- declarations.py
  - L741 `_field_gate`: `if f.fit_type in (FieldType.DROPDOWN, FieldType.RADIO, FieldType.CHECKBOX):`. L743 is then reached only by TEXT or a search TYPEAHEAD. The Q-48 F2 rule on TEXTAREA and multi-select is unchanged.
  - L873 `_disability_answer`: `if f.fit_type in CHOICE_TYPES and not bool_shaped(f):`
- facts.py
  - L497 `_leaf_fit`: `if f.fit_type not in CHOICE_TYPES or ...`. This also gives Workday prompts their "Category > Leaf" leaf fit (D-86 F7 intent).
  - L1067 `is_choice`: `_ff(field).fit_type in CHOICE_TYPES`
- questions.py
  - L85 `kind_for`: `if f.fit_type in (FieldType.DROPDOWN, FieldType.RADIO):`. A listed typeahead is now captured as a CHOICE. `field_type` keeps `f.type`.
- guards.py
  - L262 `is_choice`: optionally `pf.field.fit_type in CHOICE_TYPES or pf.field.type is FieldType.CHECKBOX`. This is the same truth table.
  - L488 `_model_row`: `if pf.field.fit_type in CHOICE_TYPES and ...`. The audit rows then carry option labels.
- apply_flow.py L384 `_shown_form`: `f.fit_type in CHOICE_TYPES`. This is harmless: the value equals `option_labels[0]`.
- Untouched: page.py, widgets.py, pagefill.py (L271/L446 already handle TYPEAHEAD), llm_fill.py L290/L295, greenhouse.py (its schema location TYPEAHEAD has no options).

Verify:
- `python tests/run_tests.py -k apply_n6a_defect_pins`: D1 passes.
- `-k apply_e2e`: the fill-llm Greenhouse test reaches ready_to_submit.
- Then the full suite.

Tester pins (add to `tests/test_apply_n6a_defect_pins.py` or a new `test_apply_fit_type.py`):
1. Parity. A TYPEAHEAD with options gives the same result as a DROPDOWN with those options for: `fit_decline`, `fit_enum` (decline, male), `fit_bool` (Yes/No both ways), `fit_text`, `fit_country` (options Singapore/Malaysia, "SG"), `fit_number` (options "0-1 years", "2-3 years", value 2), `bool_shaped` (Yes/No/decline), the memory tier (stored "Female"), `_extra_fit` kind choice, and `questions.kind_for` (CHOICE and YES_NO).
2. Search typeahead unchanged (`options=()`):
   - `fit_text("Singapore")` returns ("Singapore", ()).
   - `fit_country("SG")` returns the name.
   - `fit_bool(True)` returns ("Yes", ()).
   - `fit_decline` returns None.
   - `kind_for` returns TEXT.
   - `fit_type` is TYPEAHEAD.
3. Declarations:
   - Label "Prior employment with Acme", listed TYPEAHEAD with Yes/No options: passes `_field_gate`, same as a DROPDOWN.
   - The same label as a search TYPEAHEAD: still "not a yes/no question".
   - Disability on a listed TYPEAHEAD (Yes, I have.../No, I don't.../I don't wish to answer): same answer as on a DROPDOWN.
4. facts `_leaf_fit` on a Workday prompt TYPEAHEAD with "Category > Leaf" options gives the same result as a DROPDOWN.
5. The memory key is still "typeahead" (the memory callback receives `f.type.value`).
6. Contract: `fit_type` is not a dataclass field (`dataclasses.fields(FormField)` is unchanged), and `dataclasses.replace(f, options=())` flips it back to TYPEAHEAD.
7. Mutation checks: revert L518 and pin 1 must turn red; make `fit_type` ignore `options` and pin 2 must turn red.

Known limit (not a defect; LF §15): `page.collect_options` sets `complete = bool(options)`, so a partial suggestion list counts as complete. A value outside it gets no fit, which fails closed.
REQUEST: Coordinator: record D-167 in 02_status §4 and commit `docs(arch): Q-35 N6a D-167 FormField.fit_type for listed typeaheads`. Route the delta to the N6a engineer lane.
STATUS: open

### 2026-11-07 architect → coordinator
TYPE: handoff + request
RE: Q-74 (D-105, D-107), review `docs/reviews/Q-74.md` F1/F2/F3/F5/F8; `docs/architecture/q74_model_sees_sensitive.md`, `adr/0008-model-sees-sensitive.md`, `config/applicant.example.yaml`
BODY: Spec amended to match the fix round as built (worktree eng-q74; no shell, please commit, e.g. `docs(arch): Q-74 amend design + ADR-0008 for review F1-F8 (D-107)`). Design §1/§3: under the flag, the tier-5 corpus holds contact details only, and a protected hit is UNGROUNDED with `sensitive=True`. Notes are scrubbed and token violations reduced to their kind. The cloud-tag rule and `is_local_config` are added. §4: ten llm_fill hook points, including the `pick_option` decision (keep the full redaction), G3 ≈421, text guard ≈691, and the flag folded into the fill-cache `inputs_hash`. §6 T5 is marked superseded. ADR-0008: Decision and Consequences amended; the old "cached fills re-run once" claim is corrected. Changelog line at the top of the design.
REQUEST 1 (config/ is outside my scope): in `config/applicant.example.yaml`, replace line 3 with exactly:
`# S = sensitive: never written to logs. The AI reads S values only when apply.model_sees_sensitive is on and the model runs on this computer; except contact details, they never ground an AI-written answer (those questions wait for you).`
This supersedes the engineer's proposed wording.
REQUEST 2: record D-107 in `instructions/02_status.md` §4 (no row exists yet). Suggested row: `| D-107 | Ollama cloud model tags are not local (review Q-74 F3) | backends.is_local / is_local_config are False when the model tag ends in -cloud or :cloud (case-insensitive), even on 127.0.0.1, since Ollama forwards those to ollama.com; D-105 then stays off | Architect, 2026-11-07 | DECIDED |`.
Open questions: none.
STATUS: open

### 2026-11-07 architect → coordinator
TYPE: handoff + request
RE: Q-74 (D-105), Q-44 + Q-73, Q-76; `docs/architecture/q74_model_sees_sensitive.md`, `adr/0008-model-sees-sensitive.md`, `apply_design.md` §5.3 (D-105 amendment paragraph), `q44_refresh_from_resume.md`, `q76_application_detail.md`, `src/jobscraper/apply/contracts.py`
BODY: All three are fast-track designs, each ending with "READY TO BUILD: yes". Please review, mark them READY, and commit (I have no shell). Suggested message: `docs(arch): Q-74 Q-44 Q-73 Q-76 lean designs + ADR-0008 + contracts D-105`.
- **Q-74.** `apply.model_sees_sensitive` (owner value true in config/config.yaml) takes effect only when `backends.is_local` holds (Ollama on localhost, 127.0.0.1 or ::1). A Docker or LAN URL counts as remote.
  - It widens prompts only: `llm_extract` / `grounding_text` gain `sensitive=`, used in the tier-5 prompt and corpus.
  - It leaves alone: logging, naming, tier-1/2/4 routing, EEO, G7.
  - Contract (done, additive): `ResolveContext.model_sees_sensitive: bool = False`, plus D-105 notes on `Answer.sensitive`, `CapturedQuestion.sensitive` and `Fact.private`.
  - Q-35 merge rule: design §4.
  - Badge: "Private: local AI only". It follows the effective value.
  - 9 steps, 1 lane.
- **Q-44 + Q-73.** The profile job also writes `data/applicant.refresh.json` (resume facts only). The pure plan in applicant.py runs against the current applicant.yaml on every GET.
  - It updates or removes only `from_resume: true` entries and template placeholders. It adds new entries and skills (only skills that appear in the resume text). Owner entries and languages/links are never touched.
  - Dates are parsed deterministically. Unread dates are left null, never "present".
  - Summary card plus a collapsed log; no absolute paths.
  - 8 steps, 2 lanes (P: Python, V: Vue).
- **Q-76.** `store.last_attempts()` (one GROUP BY query) feeds a `last_attempt` pill on `/api/applications`, plus `GET /api/applications/{id}/attempts` with texts from REASON_TEXTS/STATE_TEXTS.
  - `JobDetail.vue` extraction is step 5, only after Q-75 lane I merges. Touch points: design §4.
  - 6 steps, 1 lane.
REQUEST: record D-105 in 02_status §4, and update the Q-74/Q-44/Q-73/Q-76 queue rows (status READY, design links).
Open questions: none for the owner.
STATUS: open

### 2026-11-07 architect → coordinator
TYPE: handoff
RE: Q-72 (a), D-161, D-160; `docs/architecture/mail_status_design.md` header + changelog (4), §3, §7, §8 row 7a + its note, §11.3, §15, §16, §17 (F-50l)
BODY: MS amended, READY (Q-72, D-161); please record D-161 and commit (no shell). The rule: rows 4–9 settle every matched candidate (single or ambiguous) as NONE `terminal`, and `match.signals` has no `role`/`req_id`/`thread`, and the mail is newer than every candidate's `last_event_at`, and the category is `acknowledged` or `rejected`. Then the result is SUGGEST(to=None, `maybe_untracked`), offering all matched candidates.
Exact changes: §3 `Reason.MAYBE_UNTRACKED = "maybe_untracked"` (suggested section, in `SUGGEST_REASONS`); `REASON_TEXTS` "This email may be about an application you haven't added."; `CONTRACT_VERSION` stays 1; no SKIP or COUNT key (it counts as `suggested`). §8 new row 7a plus the note "Row 7a, maybe untracked" (categories, rows 5/6/11, signals, code location, storage). §7 "Mail for untracked roles" gets one sentence. §11.3 gets a "Maybe untracked" copy row: Got it plus Open in Gmail; the app line falls back to `candidates[0].company`. §15 records the D-161 decision. §16 has 10 named oracles. §17 F-50l cites it.
Category ruling: assessment, interview and offer are already never silent (row 7 `reopen` / row 4 `several_applications`), so 7a adds only `acknowledged` and `rejected`. `withdrawn`, `posting_closed` and `kept_on_file` are excluded as noise.
Schema: no change confirmed (`mail_evidence.job_id` NULL + `candidates_json`, `to_status` NULL; `reason` has no CHECK). One flow change the engineer must make: for `maybe_untracked`, `mail_messages.job_id` stays NULL and evidence `job_id` is NULL even on a STRONG match. Today `mailstatus_flow.decide` sets both from `m.job_id` for STRONG (lines 453, 477).
This supersedes the Q-72 row's `untracked_hint` count idea; please update the queue row text.
Open questions: (1) "Find the role" link: ruled no (the Inbox has no company-search URL). Raise it if the owner wants one. (2) Expected noise: a role-less late rejection for an app already rejected will hint. Accepted as cheap; revisit after real use.
STATUS: open

### 2026-11-07 architect → coordinator
TYPE: handoff + request
RE: Q-60 MS amendment for D-157 (a)–(j), D-156 (1)(3)(4)(5); `docs/architecture/mail_status_design.md` §2.3, §3, §5.1, §5.4, §5.5, §6.5, §7, §8, §9, §10.1–§10.4, §11.1, §11.4 (new), §12, §15 R3
BODY: MS amended, still READY; no ADR change (all additive; ADR-0007 never mentioned retry_after). §3 matches lane S's contracts.py (c076f68) exactly: `AppCandidate.first_event_at`, `Reason.BACKFILLED` + `SUGGEST_REASONS`, `REASON_TEXTS` "You added this application after this email arrived." Please run `-k mail_contracts`.
Points to decide (no silent pick):
1. REQUEST (lane F, FL-1): D-157 (a) stores a `skipped/internal` row and counts `errors`, but contracts.py has no `Reason.INTERNAL` and `COUNT_KEYS` has no `errors`. MS §5.4 uses the value `"internal"` and `counts["errors"]` and marks them "not yet in §3". Recommend adding `INTERNAL = "internal"` (skipped section, in `SKIP_REASONS`) and `"errors"` to `COUNT_KEYS`; tell me and I'll add both to §3 in the same commit as the code, or lane F transcribes them into §3 too.
2. D-157 (i) says "suffix words"; lane S drops the words *anywhere* in the name and compares with any company variant; it also blocks a role/req id from lifting an extra-words sender name to STRONG (MS §7, decision step 4), where D-157 says only "→ WEAK". I wrote MS to the built code plus your "<words> at <name>" addendum. Confirm the role rule; note that a body name plus a role still gives STRONG, so "Globex Labs" mail that names "Globex" in the body with a matching role still matches the Globex application.
3. D-157 (a) isolation: I excluded the busy-DB `sqlite3.OperationalError` from per-message isolation (otherwise a locked DB would mark messages skipped forever); it keeps the §12 "stop, retry next time" row. Confirm.
4. D-157 (b) covers `mail_record` / `mail_resolve_pending` only. The duplicate path and the end-of-scan path call `mail_cursor_set` (an upsert), which can still create an orphan cursor after a disconnect. Recommend the same account check there.
5. D-157 (d): "a call was made and gave no usable answer" read as `BackendError` from `backend.complete`; a parsed but unusable reply is already an `unclear` suggestion (§6.5), so it resolves the row rather than counting a retry.
6. D-157 (f): I named the write path `store.mail_supersede(now)` (end of sync) plus accept/dismiss for their own application. Rename freely if lane F built another name.
7. D-157 (h) accept: a `backfilled` suggestion would always fail §8 row 6 on accept (the owner change is newer by definition), so MS says accept skips row 6 for it. Lane F/S must build that, or Accept gives 409 `changed`.
8. `POST /api/mail/sync` `400 {code: "no_mailbox"}` is also a command result, not a SyncCode; D-156 (5) didn't list it, so I left it out of the "Command results" paragraph.
STATUS: open

### 2026-11-07 architect → coordinator
TYPE: handoff
RE: Q-60 MS alignment (D-153, D-154 a–g, D-155 renumber); `docs/architecture/mail_status_design.md`, `mail_status_build_plan.md`, `adr/0007-mail-status-imap.md`
BODY: MS now describes the code as built on int/Q-60-mail-status e2b3998: §5.6 (F4 argument refusal, F5 URL forms, T4 punctuation), §6.2 (shared domains dropped from the gate; Reply-To still opens the gate and triggers `job_board`), §6.3/§6.4 (D-152 assessment vendors, live included), §6.5 (quote ≥ 15 chars and ≥ 3 words on the normalised quote, `model:short_quote`), §7 (employer_domains/is_shared_domain; restricted names as-written everywhere, never STRONG, not via role/req id), §8 (D-153 row 2; `as_bool`), §10.4, §11.3 (F8), §12, §13. Q-60 IDs renumbered to D-150..D-154 in docs/architecture. MS stays READY; §3 contracts unchanged (the code didn't change them).
Points to check (no silent pick):
1. D-155 says "the architect already uses the new IDs in docs/architecture/"; before this pass it didn't (D-90/D-91 were still there). Now true.
2. D-154 g names `enabled` and `model` too; only `require_auth` (transition.build_policy) is built. `MailStatusConfig` is lane F's: MS §10.4 asks it to use the `as_bool` truth table. Whether config.py may import `mailstatus.transition` is a layering question (`tests/test_layering.py`); a local copy of the same table is fine. The per-account `enabled` in `PATCH /api/mail/accounts/{id}` is JSON; I did not check the router.
3. Code comments in `mailstatus/match.py` (`_evaluate` docstring, step-4 comment) use a real employer name as the common-word example; the doc uses "Summit"/"Acme". Public repo: suggest an engineer swaps it to a neutral word at the next touch.
4. The `stale` emit and the F8 password behaviour are written from the review fix text and `MailEvidence.vue` lines 9/48; `MailCard.vue`'s consent order was not re-read.
5. `contracts.py` comment on `AppCandidate.employer_domains` ("careers_url and a non-ATS posting host") is still true as input; the filter is in the stage. No contract change needed.
STATUS: open

### 2026-11-02 architect → coordinator
TYPE: handoff
RE: Q-04, Q-05; F-10–F-12, F-20–F-25, F-30–F-40, NF-01–NF-09
BODY: Stage-B designs on `arch/Q-04-designs`: `docs/architecture/apply_design.md`, `docs/architecture/tailor_design.md`, ADRs 0001–0003, `src/jobscraper/apply/contracts.py`, `src/jobscraper/tailor/contracts.py` (stdlib only; both import). S-1/S-3 findings folded in. Proposed M20 lanes: P (profile + resolver), B (browser + Greenhouse + flow), T (deterministic tailor): apply_design §19, tailor_design §18.
STATUS: open

### 2026-11-02 architect → tester
TYPE: request
RE: NF-04, NF-01; apply_design §2.3, §20.4; tailor_design §15
BODY: (1) BLOCKING for merging `arch/Q-04-designs`: `tests/test_layering.py` must classify `apply`/`tailor` (STAGES), `apply_flow`/`tailor_flow` (ORCHESTRATOR), `applicant`/`vault` (FOUNDATION), allow apply_flow → tailor_flow and web → {apply,tailor}.contracts. Today `test_every_v2_module_is_classified` fails with "modules ['apply'] belong to no layer" (and will name `tailor` too). (2) NF-01 `git check-ignore` test. (3) Golden fixtures and oracles from tailor_design §15; Greenhouse fixtures from the S-3 recorded schemas.
STATUS: open

### 2026-11-02 architect → coordinator
TYPE: question
RE: F-12 vs F-32; F-22; scope of config/applicant.example.yaml; config data files
BODY: PRD conflicts raised, not resolved: (a) F-12 calls answer memory "resolver tier 2", F-32 lists it third; the design uses F-32's order. (b) F-22 stores attested skills in "profile overrides" (owner-protected, comment-bearing, read-only in Docker, feeds the match profile); the design uses `data/applicant.yaml` `attested_skills`. (c) `config/applicant.example.yaml` is in no role's write scope; request: add it to the software-engineer scope (lane P creates it verbatim from apply_design §5.4). (d) Researcher to write `config/questions.yaml` (apply_design §7.3.1) and `config/aliases.yaml` (tailor_design §6.1).
STATUS: open

### 2026-11-02 architect → tester
TYPE: handoff
RE: Q-19, D-67, D-68, D-69; tests/test_apply_contracts.py, tests/test_tailor_golden.py, tests/fixtures/tailor/case_a/expected.json
BODY: Designs on `arch/Q-19-tailor-patch` answer your Q-08 items (apply contracts v2, ADR-0004). Adopted as-is: your `_api` call shapes, `resolve.load_rules(path)`, `declarations.AMBIGUOUS` and `store.reap_attempts(now)`. Also set: `apply_flow.run(..., http=None, browser_factory=None)` and `computed_facts(profile, today: date)` with inclusive months and merged intervals (your 8-10 range holds). Four oracles must change: (1) `test_every_non_terminal_state_may_fail...`: exempt `submitting`; (2) `test_only_the_review_page_leads_to_submit...`: `submitted_unconfirmed` can also be reached from `verifying_email` (only after a click); (3) `test_norm_label_rules`: "Don’t you (required)" now normalises to `don't you` (apostrophes kept); (4) case A `numbers_per_bullet["2"]` is `["35%"]` (standalone numbers only; "p95" is a fact token). Your item 8: one-letter capitalised tokens are not facts. Item 4 (Greenhouse canonical by exact label vs phrase) is not decided by D-69 and is still open.
STATUS: open

### 2026-11-02 architect → coordinator
TYPE: handoff
RE: Q-22, D-70; F-31–F-39; apply_design §7.3.3, §9.1.1, §9.1.2, §9.4, §10.5, §11.5, §12.4, §14.1; apply_build_plan
BODY: Branch `arch/Q-22-workday-first`. Workday spec build-ready except selectors marked S-5 (13-item checklist in apply_design §9.4). MyGreenhouse: click-and-observe autofill, KEEP policy (resume, email, checkboxes, employer-specific declarations always ours), fallback to full fill; owner signs in once via new `python -m jobscraper apply open-profile [url]` (Q-24; default Edge profile can't be automated). Identity rule with `contact.backup_email` (§10.5), two mailboxes (§11.5), `accounts add` CLI in M20. Contracts v3 (additive, no ADR): AnswerSource, PrefillPolicy, AnswerStatus.PREFILLED, AccountStatus, SignUpOutcome, WorkdayEntry, adapter `prefill`/`read_values`, `signing_up → signing_up`. Plan: lane V (V1–V7) in M20; new WPs A03, S5, S6, F1/F4 (moved), P7, P8, B10, B11, B12; gate step 7 re-scoped. `-k apply_contracts`: 10/12, the 2 known D-69 oracle failures only.
STATUS: open

### 2026-11-02 architect → tester
TYPE: handoff
RE: Q-08 item 4; D-70; apply_design §7.3.3, §9.1.1, §9.1.2, §9.4; apply_build_plan §1 (WP-F1, WP-F4), §6
BODY: Item 4 decided (§9.1.2): link canonicals by phrase match with the one-token ≤ 4-token rule; oracle: Dataiku "LinkedIn URL" → LINKEDIN, "Github URL" → GITHUB. New oracles needed: `yes_if` worked examples (§7.3.3), KEEP/OVERWRITE tables (§9.1.1, §9.4.6), identity rules (§10.5), `to_addr` mail filter (§11.5). Workday fixtures now come from S-5 recordings at `tests/fixtures/apply/workday/<tenant>/` (scrub to the synthetic profile; hand-build `confirm.html`, `already_registered.html`). `AnswerStatus.PREFILLED` is new; `fills` stays False for it (your existing oracle holds).
STATUS: open

### 2026-11-02 architect → researcher
TYPE: request
RE: D-70; apply_design §7.3.3; WP-A03; config/questions.yaml header note
BODY: Your enum yes/no gap is answered by `yes_if` rules (§7.3.3). Please add them to `singapore_status.residency_status` (sg_citizen, sg_citizen_or_pr, sg_pr with the exclude phrases shown) and, where real forms ask Yes/No, `ns_status` / `work_pass`; replace the header's "known design limits" line with a pointer to §7.3.3.
STATUS: open

### 2026-11-03 architect → coordinator
TYPE: handoff
RE: Q-30, D-74, D-75; F-10–F-13, F-32, F-33, F-38; questions_design.md, ADR-0005, contracts v4
BODY: Branch `arch/Q-30-dynamic-fields` (uncommitted: no shell). New `docs/architecture/questions_design.md` (Application details form moved to M20, questions from applications = proposed F-13, `extra:` answers + tier 3, D-75 work rights) and `adr/0005-answer-memory-in-profile.md`. Contracts v4 (additive). `apply_design.md` gets delta pointers (§5.1, §5.2 REQUIRED_PATHS, §5.4 template `default` keys, §7.3.1, §7.4, §13, §14.3, §14.4, §18, §19, §20.2). Storage decision: answers only in `data/applicant.yaml` `extra:`; the DB keeps only the queue (`questions`, `question_sightings`); `answer_memory` is frozen. No new reason code (`unanswerable_required` + retry as a new attempt). (1) REQUEST: the scope guard refused `docs/planning/apply_build_plan.md`, so the plan insert is in `docs/architecture/questions_build_plan.md` (sections A–H); please paste it, or give the planner the task. (2) REQUEST to planner: add PRD F-13 and the F-33 D-75 sentence (text in questions_design §14).
STATUS: open

### 2026-11-03 architect → tester
TYPE: request
RE: Q-30, D-74, D-75; WP-Q0; questions_design §13
BODY: BLOCKING the merge of `arch/Q-30-dynamic-fields`: `tests/test_apply_d70.py::test_contract_version_is_3` must assert `CONTRACT_VERSION >= 3` (v4 is additive). Then the QD §13 oracles: applicant_form, web_applicant, the D-75 cases 1–15 in apply_resolve_rules (fixture `questions_d75.yaml`), apply_resolve_memory, apply_questions, web_questions, apply_flow_questions, privacy (`data/applicant.commented-backup.yaml`), and the two vitest files. Also check that no lane B oracle asserts `rule_id == ""` on an unknown answer (Q2 now sets the matched tier-2 key).
STATUS: open

### 2026-11-03 architect → researcher
TYPE: request
RE: D-75; WP-A04; questions_design §8.2–§8.3; config/questions.yaml
BODY: After WP-P9 merges, replace the four `authorised_to_work.SG/.US` and `requires_sponsorship.SG/.US` rows with two `kind: country_bool` rows (keys `singapore_status.authorised_to_work`, `singapore_status.requires_sponsorship`). Include at least the §8.3 synonyms and no country excludes (countries are detected now); put the `without …` phrases on the authorised row only, and add `exclude: [without]` on the sponsorship row. Don't touch the residency and work-pass rows (not D-75).
STATUS: open

### 2026-11-03 architect → coordinator
TYPE: handoff
RE: Q-35, Q-40, D-78 (+ D-70, D-74–D-77, D-79); F-12, F-13, F-31–F-39, NF-02–NF-07; review Q-30 F1, F3, F4
BODY: Worktree `.claude/worktrees/arch-Q-35`, branch `arch/Q-35-llm-fill` (uncommitted: no shell; please commit). New: `docs/architecture/llm_fill_design.md`, `adr/0006-llm-driven-form-filling.md`, `llm_fill_build_plan.md` (READY TO BUILD), `spikes/S-5_workday.md`, `spikes/S-5b_llm_workday.md` (tenants anonymised: A wd1, B wd5, C wd1; no names, req ids or values). Contracts v5 (`apply/contracts.py`): additive types (ValueOrigin, PageField, EntryGroup/Section, FillSource, Fact, ModelDecision, PageOutcome, SiteNavigator, GENERIC_LABELS, TRUSTED_ORIGINS, SITE_VALUE_SOURCES, AnswerSource STANDING/RESUME/JOB/RESUME_IMPORT, Answer.evidence/shown/origin/entry) + ReasonCode `model_unavailable` with copy; superseded parts (AtsAdapter fill methods, PrefillPolicy) stay until WP-C1. Key decisions: the model names the source per field, the program writes every fact-sourced value (S values never in a prompt); deterministic locks first (file, account email, declarations + new negation rule L7, D-75, sensitive tier-2, consents, extra with F1 guard); guards G1–G10 cover all six S-5b error kinds; site modules = navigation only; resume import always, then entries matched/junk deleted/descriptions rechecked; state machine, submit-once, caps unchanged. F1: generic labels matched by label + help/preceding question and only employer-scoped; F3: reviewer's fix adopted; F4: all-caps "US" → {US, job country}, a difference = conflict. Existing WPs: V2 → N1 unchanged; V4 → N4 reduced; V5 → N2 changed; V6, V7 superseded; Q1b → part of N6; B11 retired at C1; F1 → T1.
Evidence: none runnable here (no shell). Please run `python tests/run_tests.py -k apply_contracts` and `-k layering` before committing (expected green: v5 only adds; `REASON_TEXTS` covers the new code).
STATUS: open

### 2026-11-03 architect → coordinator
TYPE: question
RE: D-77 gate, D-78, NF-07, ADR-0003
BODY: (Q1, owner) The M20 gate wants real Workday submissions at the 2 approved employers. Tenant A's posting was already submitted by the spike (the duplicate guard will refuse it) and tenant B stops at a required address field until the owner answers it (Profile, or the Questions inbox). Which postings should the gate use? (Q2, owner, optional) D-78 says the LLM fills; the design keeps deterministic locks for declarations, work rights, sensitive values, consents and the owner's own answers (the model sees them as facts). Moving those to the model would change ADR-0003; I recommend keeping them. (Q3, Coordinator) Accept NF-07 deviation: a Workday attempt may take ~5–6 min with the model (`attempt_timeout_s` 900).
STATUS: open

### 2026-11-03 architect → tester
TYPE: request
RE: Q-35; llm_fill_build_plan §2 (WP-T0–T5); llm_fill_design §16
BODY: Nothing blocks the merge of `arch/Q-35-llm-fill` (v5 is additive; `test_contract_version_is_3` asserts `>= 3`). Please write T0 (contract v5) first, then T1: sanitised fixtures from the S-5b recordings (Coordinator's session scratchpad `s5b/`; personal data: rebuild with `applicant.sample.yaml` values, "Example Employer", no req ids; scan before commit) and the fake backend in `tests/llm_fill_support.py`; then T2–T5. Note the spike prompts contain contact details and nationality (the prototype sent them to the local model): never copy prompt text into fixtures; the design forbids those values in prompts and T2 asserts it.
STATUS: open

### 2026-11-03 architect → planner
TYPE: request
RE: D-78; docs/planning/apply_build_plan.md; docs/prd.md; apply_design.md pointers
BODY: (1) Paste `llm_fill_build_plan.md` §0 (WP mapping) into `apply_build_plan.md` §2.4 and mark V6/V7 superseded, V2/V4/V5/Q1b changed. (2) PRD: a D-78 sentence under F-32/F-34 (the model fills every page; facts written by the program; import from resume always), reason code `model_unavailable` in §7.2, NF-07 Workday deviation. (3) Stage-E pointers in `apply_design.md` §6, §7.2, §7.6, §9.1.1, §9.4.2 step 3, §9.4.5–§9.4.10, §15 to `llm_fill_design.md` (list in its §15).
STATUS: open

### 2026-11-03 architect → coordinator
TYPE: handoff
RE: Q-35 amendment (stage E READY WITH FIXES: `docs/reviews/Q-35-design.md` H1–H7, M1–M14; tester TR-1–TR-13; D-81, D-82, D-83)
BODY: Worktree `.claude/worktrees/arch-Q-35` (no shell: uncommitted, please commit). Amended: `docs/architecture/llm_fill_design.md` (rewritten in place, same section numbers), `llm_fill_build_plan.md` (rewritten; every WP has a STATUS; RUNNING ones have an "Amendment delta"), `adr/0006-llm-driven-form-filling.md` (status + "Amendment" section; the decision stands), `spikes/S-5b_llm_workday.md` (rule ids only), `src/jobscraper/apply/contracts.py` (still v5, additive only).
Change log (finding → where it is closed):
- H1 grounding → LF §7 G3 (copy rule: every content token of a TEXT / entry TEXTAREA / text `keep` value in the evidence; compose rule = `grounded` only for free TEXTAREA outside entries; entry corpus = block + entry facts), §6.4 `recheck` (copy task; unknown/rejected → optional cleared, required unknown, never kept), §16 oracles.
- H2 fact refs → G2 (a) scope incl. TR-3, (b) relevance via `facts.relevant` (§5.3), (c) value, (d) polarity: program option used only with a tier-2/`extra` label match or when the model's option equals it, else unknown (no "program wins"), (e) no fit → G4 + G5. Audit: model-chosen facts = tier LLM, `fill:v2` (§7 answer mapping; ADR amendment).
- H3 untrusted site values → new G9 (clear / reset / untick / PREFILLED 0.5 "unverified"; E6 in entries), §3.2 `reset()`, G5 covers optional Yes/No.
- H4 privacy (TR-1) → new §6.5: `facts.s_values`, `llm_fill.redact` on the whole user prompt of every call, `current_set` withholding rules, redacted debug dump.
- H5 other employers → G12 + `ResolveContext.other_employers`; generic labels cite only this employer's `extra` (§12.1); G8 trusts MyGreenhouse only for non-TEXTAREA, non-cover-letter fields.
- H6 attachments (TR-8) → L1 (keep only files in `ctx.uploaded` name+SHA-256; page-text clause only with one FILE input; cover letter/transcript never the resume), L1b (required cover letter composed + uploaded).
- H7 revealed/required fields → §8 steps 10 and 12 (re-read rounds ≤ 2; `page.scan_required` before Next) and "Before Submit" (scan before the click); oracles in T3/T4.
- M1 → §4 lock order L1, L2, L4/L5, L6, L3/L7 (an unknown consults L6) + §12.1 context-less qualified label (`| @step#n`). M2 → G7 word list. M3 → §3.3 + `AttemptContext.pre_import` (Greenhouse snapshot). M4 (TR-2) → §13.3/§14: cache stores the ModelDecision only, key + `inputs_hash`, row `facts_used_hash`, guards re-run on replay. M5 → `ResolveContext.resume_entries` (owner WP-N6b, `tailor_flow.resume_entries`), G3/G6 reject with no block, `profile_incomplete` check (§5.2), WP-F3 dropped. M6 → `FillServices` Protocol (contracts) + pinned-signature table (LF §8), `classify` before step 9 and the corrective pass, `PageOutcome.transport_failed`. M7 → §9.1 `step_id` `_<N>` + loop guard on field signatures (§8). M8 → §3.2 Enter rule. M9 (TR-7) → §8 step 7 (nothing changed) / step 9, E7. M10 → BP §0 (I1, L1/L2, F2, W8, F3 dropped), §7 = 5 Greenhouse dry runs, N6 split into N6a/N6b. M11 (D-81) → §11 deadline, §13.1, §13.4 (`attempt_timeout_s` 420, `attempt_timeout_workday_s` 900, both exclude the IMAP wait; checked before each chunk and before typing). M12 → G11. M13 (D-83) → G8 (required `resume_import` kept only when grounded), BP §7 row-by-row audit. M14 → §3.2 strict read-back for every family, search miss clears.
- TR-4 → §6.2 exported constants, FIELDS block last, `via` on every decision, `read_page(rng=)`. TR-5 → `facts.today_sg`, `FillServices.today/now`, `apply_flow.run(now=None)`. TR-6 → `keep_alive` only when set (§6.3, §13.4); T4 pins `fill: rules`. TR-9 → list rules renamed LL1–LL4, T3 owns `apply_pagefill`, T5 owns `apply_questions_page`. TR-10 → E2 overlap coefficient ≥ 0.5 (≥ 0.8 no employer), optional resume/job choice without G5 = 0.8, `second_opinion: false` → unknown, module constants. TR-11 → confirmed (§6.2). TR-12 → G11 + optional WP-T6 eval. TR-13 → noted (dry runs prove widget fidelity).
- D-82 → §4 heading, §15, ADR. D-83 → G8, §15, BP §7.
Nothing accepted without a fix: every HIGH and MEDIUM is fixed.
Contracts (additive, v5): `ResolveContext.resume_entries`, `.other_employers`; `AttemptContext.pre_import`, `.uploaded`; `PageOutcome.transport_failed`; `FillServices` Protocol (backend, model, rules, cfg, today, now, deadline_left, classify, cache_get, cache_put, log); `ModelDecision.via` comment widened.
Running WPs, exactly what changes: T0 + oracles for the new fields/Protocol; T1 pre-filled sample phone/address on wd_a My Information, the fake backend routes on the exported constants and parses the FIELDS block, a reveal stub; T3 + M8/M14/H3 widget oracles and the new `tests/test_apply_pagefill.py`; R1 none (optional `rng`, `pre_import` origins, else R3); R2 strict read-back for all families, optional search miss clears, Enter rule, `reset()` (else R3); N2 `step_id` `_<N>`, `workday_entry: manual` (else N6a); N3 `pre_import` snapshot before the MyGreenhouse click (else N6a); N5 `fill_cache` shape (+ `inputs_hash` key, `facts_used_hash`), `attempt_timeout_workday_s`, `max_reveal_rounds`, `workday_entry`, optional `keep_alive` (else N6b migrates); N1, N4 unchanged.
WPs READY now: T2, T4, T5, T6 (optional), M1–M5, Q5, R3; N6a after lanes M and R merge, N6b after N6a. C1 after the gate.
Evidence: none runnable here (no shell). Before committing please run `python tests/run_tests.py -k apply_contracts` and `-k layering` (expected green: only defaulted fields and a new Protocol were added).
STATUS: open

### 2026-11-03 architect → coordinator
TYPE: question
RE: D-83 gate; owner
BODY: For the owner: the gate's Workday postings need fresh approval (D-83). Tenant A's spike posting is already submitted (duplicate guard) and tenant B stops at the required address field until the owner answers it in Profile. This replaces my earlier Q1; Q2 is answered by D-82 and Q3 by D-81.
STATUS: open

### 2026-11-03 architect → tester
TYPE: request
RE: Q-35 amendment; llm_fill_build_plan §2 deltas
BODY: The amendment is in (`llm_fill_design.md` §3.2, §6.2, §6.5, §7, §8, §16; contracts v5 additions). For the running WPs: T0 add the new-field and `FillServices` oracles; T1 pre-fill wd_a My Information with the sample phone/address, route the fake on `SYSTEM`/`SECOND_SYSTEM`/`PICK_SYSTEM`/`RECHECK_SYSTEM`, parse the `FIELDS (JSON):` block (last before the fixed final line), add the reveal stub; T3 add the M8/M14/H3 widget oracles and `tests/test_apply_pagefill.py`. T2, T4, T5 are READY with the inputs listed in the plan; T6 (eval) optional. Rule ids changed: list rules are now LL1–LL4; locks stay L1–L7; guards are G1–G12; entries E1–E7.
STATUS: open

### 2026-11-03 architect → coordinator
TYPE: handoff
RE: Q-45 and lane M gaps (D-84, D-85, D-86; lane M outbox questions; lane R R3 choices); contracts v5 + tailor v2 (additive)
BODY: Worktree `.claude/worktrees/arch-Q-35` (no shell: uncommitted, please commit). Change log (item → where):
- Task 1, contracts (`apply/contracts.py`, still v5, additive): `QuestionReason.COMPOSE_NEEDED`, `AnswerSource.COMPOSED`, `ResolveContext.job_title` (closes Q-27's first half), `AttemptContext.composed`/`composed_files`, `PageOutcome.compose_needed`. The chip copy for `compose_needed` is in LF §19.6 (owned by WP-K2's QuestionCard edit). `tailor/contracts.py` v2, additive: `ComposeRequest`, `ComposeResult`, `COMPOSE_VERSION`, IssueCode `VERB_UPGRADE`/`PRIVATE_VALUE`/`OTHER_EMPLOYER`/`PLACEHOLDER`. No `FillServices` member was added, so T0's isinstance oracle is unaffected.
- Task 2, Q-45 → LF new §19 (targets, fill_page step 7b, flow loop, the tailor's compose call, checks C1–C7 reusing `validate.numbers`/`facts` and `UPGRADE_WORDS`, owner opt-in `apply.compose.enabled` default false, length limits, S values redacted and checked, audit holds the whole text, copy), L8, §6.1/G3 (targets never go to the page model), §13.4 config, ADR-0006 amendment bullet, `tailor_design.md` §17 pointer. Build plan §5b: WP-K1 READY, WP-K2 READY once `int/Q-35-M` is in personal, WP-K3 not READY (after R3, N6a, K1, K2), WP-T7 READY (skip-clean). The gate runs with composing off.
- Task 3, lane M gaps: (1) `links.*` facts outside entry groups → G2(a), as built. (2) profile_gap without a tier-2 row → G2(f) documents lane M's `_rule_gap` fallback; tier-1-only paths (`contact.city`, `links.*`) stay `no_rule` until tier-2 rows exist (researcher request below). (3) One-word labels generic → §12.1, as designed (only L6 reuse and capture are narrowed). (4) G12 (and R4) rejects captured `no_rule` → §11, as designed. (5) Extra kwargs → §8's pinned table now carries every built signature (decide's `rules/sections/model/prompt_hashes/cfg/blocks` with "must pass" notes, `Decision` fields, `Chunk.locked`, `CallLog`, `pick_option` `sensitive`/`deny`, `lock_page` `page_text`, `field_sig` `key` required, `read_page` extras, widgets). L1b's cover-letter question → Q-45.
- Task 4: D-84 R1 → G12; R2 → G5 + G2(d); R3 → E4; R4 → G2(b) + new G13 (any source). D-85 → LF §9.2 and AD §9.1's `otp_pattern` row. D-86 F7 → G2(e); F8 → §13.3 (HMAC `field_sig`); F9 → §11 + §19.
- Lane R's R3 choices: (a) deadline → `transport_failed` "transport: timed out": **accepted**, with one flow rule (LF §8, §11): N6a checks `services.deadline_left() <= 0` and then ends `failed(error)` "timed out on <step>", else `model_unavailable`. (b) Cache stores no `second`/`corrective` replies: **accepted** (§13.3): replaying a stored second opinion would count one run as two, so G5 re-asks on replay.
- Also seen: the tester/lane R question on `stubs/enter_form.html` (M8). The rule stands; the M14 read-back oracle should move to a prompt outside any form, as lane R proposes.
Changes for already-built code: lane M K2 (compose targets out of the page schema; L8; notes); lane N/N6a the deadline split above; nothing else built changes.
**One known red:** `tests/test_apply_questions.py::test_question_contract_types_are_the_ones_the_design_names` pins the `QuestionReason` set exactly (line 119), so `COMPOSE_NEEDED` breaks it by design. The tester adds "compose_needed" to that set in the same merge (D-86 F9 asked for the member).
Evidence: none runnable here (no shell). Please run `python tests/run_tests.py -k apply_contracts`, `-k apply_questions`, `-k tailor` and `-k layering` before committing. Expected: green apart from the pin above; only defaulted fields, new enum members and new dataclasses were added.
STATUS: open

### 2026-11-03 architect → researcher
TYPE: request
RE: LF §7 G2(f); D-74 rule rows
BODY: Tier-2 rows (A03 style) for tier-1-only profile paths that forms ask as single questions, so an empty one is captured `profile_gap` instead of `no_rule`: `contact.city`, `links.linkedin`, `links.github`, `links.portfolio` (labels and synonyms only, generic; no values). Private paths such as the postal code don't need one: they are listed as set/empty, so G2(c) already captures them as `profile_gap`.
### 2026-11-02 architect → coordinator
TYPE: handoff
RE: Q-60 / F-50 (D-90, D-91); docs/architecture/mail_status_design.md, mail_status_build_plan.md, adr/0007-mail-status-imap.md
BODY: Stage-B design for application status from email is READY for stage E. Written only in `.claude/worktrees/feat-Q-60/` on `int/Q-60-mail-status`; not committed (no shell): please commit as `docs(architecture): Q-60 stage-B design, build plan, ADR-0007`.
- Placement (ADR-0007): foundation `imapread.py` (the only F-50 IMAP code; web/ may not import it) + stage package `mailstatus/` (contracts, rules, match, transition, model; pure) + orchestrator `mailstatus_flow.py`. The web timer (`web/mailsync.py`) spawns `python -m jobscraper mail sync` as its own child (not JobManager), with a DB lease (`mail_sync_runs`, BEGIN IMMEDIATE + heartbeat).
- Contracts: new `mailstatus/contracts.py` v1 (full listing in MS §3; WP-S0 transcribes it, and I sign off at review). `apply/contracts.py` is untouched.
- New tables (SCHEMA_VERSION 4 → 5): `mail_accounts`, `mail_cursors`, `mail_messages`, `mail_evidence`, `mail_sync_runs`. If the concurrent session also bumps to 5, make it 6 at merge, with the comment listing both (MS §9).
- Lanes: S (S0–S3 stage), I (I1 imapread, I2 apply/mail Spam fix, U1 Settings card, U2 Applications), F (F1 store, F2 config, F5a web backend, F3 flow, F4 CLI, F5b real children). Tester T0–T6, researcher R1 (rules file) + R2 (spike, owner consent), planner P1. T0 must merge together with S0 (the layering sets).
- Decided (MS §6.4, §8, §15): HireVue on-demand → assessment; posting closed and lone kept-on-file → suggestions; `assessment` added to `applications.statuses`; model-tier verdicts never automatic; automatic changes need Gmail DKIM/DMARC pass and (except acknowledgements) not Spam; no unmatched-mail list; no X-GM-RAW; no IDLE.
- D-91 readings (no contradiction): "anything else → suggestion" = forward moves below the confidence bar plus the explicit cases. Backwards, same-status and stale (older than an owner change) mail change nothing and raise no suggestion. "Confident" excludes model-tier verdicts.
Requests:
(1) Add `config/mail_rules.yaml` to the researcher's write scope (`.claude/scopes.json`) for WP-R1.
(2) Add `JOBSCRAPER_MAIL_SYNC=0` to the dev-instance command in CLAUDE.md: a copied DB would otherwise read the real mailbox (MS §15 R3).
(3) If ADR-0007 is taken on `personal` at merge time, renumber this ADR and its two references.
Owner questions (recommendations in MS §15; none blocks the build): which mailboxes (application Gmail first); keep automatic offer and rejected under the bar; the `assessment` status; the owner triggers the first real sync after the merge go-ahead.
Evidence: none runnable (docs only). After the commit, `python tests/run_tests.py -k layering` should stay green (no code changed).
STATUS: open

### 2026-11-02 architect → coordinator
TYPE: handoff
RE: Q-60 stage-E amendment E1 (Oleeo tenants); mail_status_design.md §3, §6.1, §7, §9, §14; mail_status_build_plan.md WP-S1, S2, F1, T3, R1, R2
BODY: E1 is in.
- §6.1: platform keys `tenant_from_subdomain` (strict subdomain of a platform domain; at most one tenant flag per platform) and `tenant_sites`; Oleeo `{id: oleeo, kind: ats, domains: [tal.net], tenant_from_subdomain: true, tenant_sites: [tal.net]}` in the seed; Workday gains `tenant_sites: [myworkdayjobs.com]`.
- §7: `compact()` (normalised, spaces removed); the `tenant` signal covers both flags and compares in compact form against `app.tenants` and every company variant (both flags: yes, as asked).
- §3, §9: `mail_match_context` returns raw `tenant_hosts` (attempt `tenant_host` plus the hosts of `jobs.url`, `applications.url` and `companies.careers_url`); `match.tenants_from_hosts` builds `AppCandidate.tenants`.
- BP: S1, S2, F1, R1 and T3 point at E1; R2 is DONE.
CONTRACT_VERSION stays 1: only the `AppCandidate.tenants` comment changed.
One deviation from the literal ask: the host suffixes come from the rules key `tenant_sites` rather than a hard-coded `myworkdayjobs.com` / `tal.net` list in store or code. That keeps "a new ATS without code edits" (§14) true and keeps domain data out of `store.py`. Please commit as `docs(architecture): Q-60 E1 Oleeo tenants (tenant_from_subdomain, compact match)`.
STATUS: open

### 2026-11-08 architect → software-engineer (cc coordinator, tester)
TYPE: handoff
RE: Q-80 D-169b; answers the engineer's 2026-11-08 question (D-91 pin "Can you confirm you are clear of any conflict of interest?"); apply_design.md §7.5 D-164 step 2, step 4, pin table, header delta; KA-2
BODY: Yes, accept the modal, but only directly before a LEAD. Spec (§7.5 D-164 step 2): a MODAL run (can you, could you, would you, will you), with an optional please after it, is dropped only when a LEAD comes immediately next; the LEAD is then dropped as before, so shape B applies. A modal anywhere else is not dropped and gives no frame. It is not a PREFIX run and does not count toward the 3-token cap. Gate 1 (step 4) never drops the MODAL run. New pin rows: "Can you confirm you are clear of any conflict of interest?" → Yes (freedom form, `conflict_audit_independence: false`); "Can you tell us whether you are a PEP?" → No; "Can you sign a non-compete?" → unknown (no frame; gate 2 willingness also fails). The existing D-91 pin keeps its expected Yes. Contracts unchanged, no ADR (additive to D-164). Coordinator: please commit as `docs(architecture): Q-80 D-169b modal before a LEAD in question_frame`.
STATUS: open

### 2026-11-08 architect → coordinator, software-engineer, tester (Q-82, D-170)
TYPE: handoff
RE: Q-82; `docs/reviews/Q-80-declarations.md` MEDIUM 1–3; `docs/architecture/apply_design.md` line 4 (delta), §7.5 D-164 step 3 (shape A line, D-170 pointer), new D-170 block and oracle table after the D-164 table; KA-2
BODY: D-170 was free (grep of `instructions/` and all `*.md` found no D-17x). Please record it in 02_status §4: "D-170 | Q-82 | a status declaration (standing classes + disability) is answered only when the whole label is one status question: closed-span vocabulary per class, one-clause rule, `status` only at the end of a class noun phrase, the same check on a single checkbox | architect | DECIDED". Commit suggestion: `docs(architecture): Q-82 D-170 one status question per declaration label`. Contracts unchanged, no ADR: it tightens D-164 and changes no interface. No D-164/D-169b pin-table row changes. No existing test pin changes either: I replayed every declaration label in `tests/` by hand against the rule (F1_LABEL, D-89, D-90a, D-91 freedom forms, contracts tests, llm_fill probe). Review-table rows that change: the 16 over-answers → unknown, plus "Do you have a non-compete you'd like us to buy out?" (No → unknown, the review called it arguable). "Specify if you have a criminal record and the offence" stays No (benign).
CODE DELTA (one lane, `src/jobscraper/apply/declarations.py` only; no new imports, `re` is already imported):
1. `_STATUS_RUNS`: drop `("status",)`.
2. After `STANDING_DECLARATIONS`, add `_STATUS_CLASSES = STANDING_DECLARATIONS | {L.DISABILITY}`, `_STATUS_FILLER` (the 72 SHARED words of §7.5 D-170), `_CLASS_FILLER: dict[DeclarationLabel, frozenset[str]]` (the 8 per-class lists, verbatim from §7.5), `_CLAUSE_OPENERS = _STATUS_STARTERS | {"you", "i", "you're", "you've", "i'm"}`, `_NUMBER = re.compile(r"[0-9]{1,3}")`.
3. New helpers:
```python
def _class_spans(toks, c):
    spans = _spans(toks, _PHRASE_TOKENS.get(c, ()))
    if c is L.GOVERNMENT_EMPLOYMENT:                 # D-87 "(gov or mil) and excl"
        spans += _spans(toks, _MILITARY_TOKENS)
    return spans

def _employer_spans(toks, employer_names=()):
    out = _spans(toks, THIS_EMPLOYER_RUNS)
    for name in employer_names:
        want = _company_tokens(name or "")
        for i in range(len(toks) if want else 0):
            for j in range(i + 1, min(len(toks), i + len(want) + 2) + 1):
                if _company_tokens(" ".join(toks[i:j])) == want:   # equality, not the prefix rule
                    out.append((i, j))
    return out

def _one_status_question(toks, classes, employer_names=(), extra_runs=()):
    """D-170 rules 1-3 (apply_design §7.5)."""
    toks = strip_ns_exclusions(list(toks))
    classes = set(classes)
    per_class = [_class_spans(toks, c) for c in classes]
    if not classes or not all(per_class):
        return False                                             # rule 2
    anchors = [s for spans in per_class for s in spans] + _spans(toks, _STATUS_RUNS)
    covered = {i for a, b in anchors + _spans(toks, _FREEDOM_RUNS) + _spans(toks, extra_runs)
               + _employer_spans(toks, employer_names) for i in range(a, b)}
    filler = _STATUS_FILLER.union(*(_CLASS_FILLER.get(c, frozenset()) for c in classes))
    if any(i not in covered and t not in filler and not _NUMBER.fullmatch(t)
           for i, t in enumerate(toks)):
        return False                                             # rule 1
    cuts = [k for k in range(1, len(toks) - 1)
            if toks[k] in ("and", "or") and toks[k + 1] in _CLAUSE_OPENERS]
    bounds = [0, *cuts, len(toks)]
    return all(any(a <= s < b for s, _e in anchors) or all(t in _STATUS_FILLER for t in toks[a:b])
               for a, b in zip(bounds, bounds[1:]))              # rule 3

def _status_tail(toks, classes):
    """D-170 rule 4: "status" opens shape A only as the last token of a class noun phrase."""
    if len(toks) < 2 or toks[-1] != "status":
        return False
    head = toks[:-1]
    covered = {i for c in classes for a, b in _class_spans(head, c) for i in range(a, b)}
    return bool(covered) and all(i in covered or t in _NOUN_FILLER or t == "your"
                                 for i, t in enumerate(head))

def _strip_attest_lead(toks):
    for lead in sorted(_ATTEST_LEADS, key=len, reverse=True):
        if tuple(toks[:len(lead)]) == lead:
            return toks[len(lead):]
    return toks
```
   (`attestation_polarity` may use `_strip_attest_lead` too. Same behaviour.)
4. `question_frame(label_toks, classes, f, employer_names=())`: steps 1–2 unchanged; replace the shape tail with
```python
    classes = set(classes)
    shape_ab = (toks[0] in _STATUS_STARTERS or any(tuple(toks[:len(r)]) == r for r in _FRAME_A_RUNS)
                or any(_has_run(toks, r) for r in _STATUS_RUNS) or _status_tail(toks, classes)
                or (lead and any(tuple(toks[:len(r)]) == r for r in _FRAME_B_RUNS)))
    if shape_ab and (not classes or not classes <= _STATUS_CLASSES
                     or _one_status_question(toks, classes, employer_names)):
        return True                                              # D-170 for the status classes
    return _noun_phrase(toks, classes, f)
```
5. `_bool_answer(..., employer_names: tuple[str, ...] = ())`:
   - Non-checkbox branch: pass `employer_names` to `question_frame`.
   - Checkbox branch, right after `if polarity is None: return _ended(...)`:
```python
        if cls is not L.NDA_WILLINGNESS and cls in _STATUS_CLASSES and not _one_status_question(
                _strip_attest_lead(toks), {cls}, employer_names,
                extra_runs=_NEGATIVE_ATTESTATIONS + _POSITIVE_ATTESTATIONS):
            return _ended(f, name, "checkbox statement not recognised")   # D-170 rule 5
```
6. `answer()`: `names = employer_names_of(ctx)`. Pass `employer_names=names` to both `_bool_answer` calls, and call `_disability_answer(f, value, names)`, which forwards the names to its `_bool_answer`.
Verify: `python tests/run_tests.py -k declarations` (then `-k apply_contracts`, `-k llm_fill`, `-k layering`, full suite). Expect every existing test to pass unchanged.
TESTER PINS (new file `tests/test_apply_declarations_d170.py`, reuse `test_apply_declarations_q48` helpers as d164 does): every row of the §7.5 D-170 oracle table. Separate tests for:
- rule 1, the modifier rows (lawyer, screening officer, record check, law firm);
- rules 1 and 3, the compounds (right to work, relocate, eligible, valid work permit, "working in Singapore");
- rule 4 (the two "status" rows, plus the two kept "status" rows);
- rule 5 (the two checkbox rows);
- the kept rows (F1_LABEL with `required=False` as `test_f1`; "aware of any conflict of interest with Acme" needs the employer in ctx).
Note: rule 2 has no live probe. Pin it with a label/description pair: label "Do you have any?", description "Criminal record" → unknown. Every token of that label is filler, so only rule 2 stops it; today it fills No.
STATUS: open

### 2026-11-10 architect → coordinator, software-engineer, tester (Q-90, Q-91, Q-92 F3/F5; D-176)
TYPE: handoff + question
RE: Q-90 (review `docs/reviews/Q-83-declarations.md` MEDIUM-1, LOW-1, LOW-2), Q-91, Q-92 F3/F5 (`docs/reviews/Q-35-N6b.md`); `docs/architecture/apply_design.md` line 4, §7.5 classifier line, table row `criminal_record`, D-176 block after D-171; `docs/architecture/llm_fill_design.md` §7 G12 row, §13.3; `src/jobscraper/apply/declarations.py` (engineer, one lane)
BODY: Spec of record is the D-176 block in apply_design §7.5 (A) and its 39-row oracle table (D, for the tester to copy). Contracts, reason codes and profile keys unchanged, so no ADR (a refinement of D-171 under ADR-0003). Q-92 F3 and F5 are spec notes that match the code as built (N6b b684d2a); no code change. No existing pin changes its expected answer.

**C. Code delta (`src/jobscraper/apply/declarations.py` only)**
1. `PHRASES[L.CRIMINAL_RECORD]` += `"found guilty"`.
2. Only if the Coordinator approves Q1 (option A): `PHRASES[L.REGULATORY]` += `"disqualified as a director", "disqualified as director", "disqualified from acting as a director", "disqualified from being a director", "director disqualification"`; `_CLASS_FILLER[L.REGULATORY]` += `company companies`. Option B: put the same five runs in `UNCLASSED_MARKERS` (item 3) and add nothing to the class.
3. New `UNCLASSED_MARKERS = _toks(("court order", "court orders", "injunction", "injunctions", "restraining order", "refused entry", "denied entry", "deported", "deportation", "dismissed", "asked to resign", "terminated for cause", "legal proceedings", "litigation"))`, defined after `_toks` (line ~411). In `classify()`, after the `ATTESTATION_MARKERS` check: `if any(_has_run(toks, r) for r in UNCLASSED_MARKERS): return AMBIGUOUS` (toks = `label_norm.split()`; label only). Do **not** add them to `ATTESTATION_MARKERS`: `_compound_unclassified` reads that set, and the employer-class compound "…worked for Acme, or have you ever been deported?" would then answer one clause.
4. `_STATUS_FILLER` −= `last past year years month months since` (65 → 58). New `_TIME_FILLER = frozenset("last past year years month months since".split())`.
5. New `_OTHER_PARTY = frozenset("employer employers company companies client clients auditor auditors regulator regulators authority authorities".split())`.
6. `_one_status_question` (signature unchanged; `narrowing_ok` keeps its name and meaning: the stored value is false, read before the D-91 inversion):
   - `shared = _STATUS_FILLER | _TIME_FILLER if narrowing_ok else _STATUS_FILLER`; build `filler` from `shared` instead of `_STATUS_FILLER`; NARROWING as today.
   - `emp = _employer_spans(toks, employer_names)` once; `places = _place_spans(toks, classes, standing_cover) if narrowing_ok else []`; `covered` uses `emp` and `places`.
   - Rule 3 lead-in test: `all(t in shared for t in toks[a:b])` (was `_STATUS_FILLER`).
   - Rule 6b, after rule 6: for each piece `(a, b)`, `first = min((s for s, _e in anchors if a <= s < b), default=b)`; fail when `any(toks[i] in _OTHER_PARTY for i in range(a, first))` or `any(a <= s < first for s, _e in emp)`.
   - Docstring: add "6b no third party in the subject zone; time words and place qualifiers count only when `narrowing_ok`".
7. The comment above `_NARROWING_FILLER`: one line for D-176 (time and place are value-sensitive too).
Verify (engineer): `python tests/run_tests.py -k declarations` stays green (122 today) plus the tester's new file; then `-k layering`, `-k apply_flow`, `-k apply_e2e` (the full suite skips Edge silently: handover).

**D. Tester:** new file `tests/test_apply_declarations_d176.py`, gated on `declarations:_TIME_FILLER`, with the same `_run` helper as the d171 file; rows 1–38 of the D-176 table (row 39 is the existing suites). Row 32: write it for the option the Coordinator picks. Rows 33–36 also assert `D.classify(_n(label), "") is D.AMBIGUOUS`.

**Questions for the Coordinator**
- Q1 (owner data meaning, your call): map "disqualified as a director" onto `regulatory_disciplinary` (option A: it widens what the owner's `false` states, as D-87 widened `non_compete`), or keep it unknown on purpose (option B)? I recommend A: a new grad cannot have been a director, and D-87's intent is "answer the standard declarations". B is the strict ADR-0003 reading. Neither touches `data/`.
- Q2 (D-84 R1 wording): the code subtracts the applicant's own employers in G12 only for composed texts. I amended LF G12 to match the code and gave the reason (a stored `extra`/kept text that names a past employer may have been written for that employer). Confirm, or rule that D-84 R1 covers every G12 source; that would need a code change in `facts.other_employers`.
- No new profile key is proposed. If one is wanted later for the four AMBIGUOUS families, it defaults to null (asked), not false: they are outside D-87 and D-55.

**Not done in this session:** I had no shell tool, so I made **no commits** and **did not run** `-k declarations`. The Coordinator (or the next agent with a shell) should commit on `eng/Q-90-declarations` as two commits: `docs(architecture): Q-90/Q-91 D-176 value-sensitive place and time, rule 6b, six labels` (apply_design.md + this outbox entry) and `docs(architecture): Q-92 F3/F5 spec notes` (llm_fill_design.md). No code was changed, so `-k declarations` should still give 122/122.
STATUS: open
