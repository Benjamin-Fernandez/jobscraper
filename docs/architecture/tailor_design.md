# Resume tailor design (KA-4)

**Stage B dossier** for PRD F-20–F-25 (`docs/prd.md` r1). Queue Q-05. Author: architect, 2026-11-02.
**Status:** DRAFT for stage E cross-review. Contracts: `src/jobscraper/tailor/contracts.py` (CONTRACT_VERSION 1). Related: `apply_design.md` (the hand-off in §12), ADR-0003 (fail-closed principle).
**Inputs:** `docs/research/resume_tailor_brief.md` §4, §5, §7, §8 and "Recommended design".

Truthfulness rule for the whole feature: **code decides facts, the model only rewords.** Employers, titles, dates, degrees, institutions and locations are copied by code and never sent for rewriting; every rewritten bullet passes a deterministic validator or the original text is kept.

---

## 1. Responsibilities and boundaries

The tailor: parses the owner's resume once into a structured master; extracts a job's key terms; maps them to the master; computes "JD keyword coverage"; rewrites truthfully (variant spellings first, then the model per entry); validates; renders a parse-safe DOCX (and PDF through Word); stores it temporarily; reports missing terms; hands the file to auto-apply.

It does not: add any skill, tool, employer, title, date, degree or number; generate cover letters; judge fit; call a cloud model; keep files beyond D-59.

---

## 2. Components and module map

```
src/jobscraper/
  tailor_flow.py        ORCHESTRATOR  tailor(...), tailor_for_apply(...), purge hook wiring
  tailor/               STAGE
    __init__.py         engineer; exact content: """Resume tailor stage package (docs/architecture/tailor_design.md)."""
    contracts.py        architect (done)
    master.py           master parse (LLM + leaf check), cache load/save                 §3
    terms.py            matcher, dictionary (aliases.yaml), JD extraction, required/preferred, knockouts   §4
    mapping.py          classify terms against the master; coverage                      §5
    rewrite.py          deterministic swaps, reorder, LLM entry rewrite, summary rewrite  §6, §7, §9
    validate.py         bullet + summary validator, resume-wide invariants               §8
    render.py           DOCX template, Word-COM PDF, page ceiling, round-trip check       §10
    storage.py          paths, file naming, retention purge                              §11
config/aliases.yaml     researcher-owned data (format §6.1)
data/ (gitignored)      master_resume.json · tailored/<job_id>/<First>_<Last>_Resume.docx|pdf
```

**Layering:** `tailor/` imports only `tailor.contracts`, foundation (`store` is not needed by the stage; `backends` objects are passed in), stdlib, `python-docx`, `pypdf`, `yaml`, and `pywin32` (optional, render only). Functions the stage needs from other stages are injected by `tailor_flow`: `extract_text(path) -> str` and `find_resume(dir) -> Path` and `file_hash(path) -> str` from `profile/resume_ingest.py`, `html_to_text(s) -> str` from `scrape/adapters.py` (the same pattern as `keywords.overlap` being handed to the filter). `tests/test_layering.py` changes are in `apply_design.md` §2.3 (STAGES += tailor; ORCHESTRATOR += tailor_flow; `apply_flow → tailor_flow` allowed; web may import `tailor.contracts`).

**Orchestrator API:**

```python
def tailor(cfg, store, job_id: str, *, backend, report_only: bool = False,
           force: bool = False) -> TailorResult
def tailor_for_apply(cfg, store, job_id: str, *, backend) -> TailorResult   # returns the current file if any (§11.2), else tailor()
def purge(cfg, store, now: str) -> int                                        # called by cmd_purge and the end-of-run purge
```

`tailor()` steps: load applicant + master (parse if the resume hash changed) → JD text (fetch if missing) → terms → mapping → coverage before → swaps → [LLM rewrite + validate, summary] → reorder → page ceiling + render → round trip → coverage after → store row + files. Any exception → `TailorResult(ok=False, status=failed, error=<class: message without resume text>)` and a `failed` row; `tailor_for_apply` then hands back the original resume path (apply design §4.1).

---

## 3. Master resume (F-20)

### 3.1 Cache

`data/master_resume.json` = `{"version": 1, "resume_hash", "source_name", "page_count", "parsed_by", "parsed_at", "master": {…MasterResume as JSON…}}`. `master.load(path, resume_hash, text) -> Optional[MasterResume]` returns it only when `resume_hash` matches **and** the leaf check (§3.3) passes against the current text (so a hand edit is allowed but still checked). Otherwise `master.parse(text, backend)` runs and the file is rewritten atomically.

`page_count`: PDF → `len(PdfReader(path).pages)`; DOCX → Word COM `ComputeStatistics(2)` (§10.3), else 1 when Word is unavailable.

### 3.2 Parse (one LLM call per resume hash; temperature 0)

System prompt (`master.SYSTEM_PROMPT`):
```
You split a resume into structured JSON. Copy text EXACTLY as it appears in the resume:
same words, same spelling, same capitalisation, same numbers. Do not fix, shorten, merge,
reword or translate anything. Leave out bullet symbols (•, -, ▪). If a value is absent, use "".
Each job, degree, project or role is one entry. Each bullet point is one string in "bullets".
Skills-like sections (lists of items) go in "items", one item per comma- or line-separated value.
```
User: `RESUME TEXT:\n<text, first 20000 chars>`. `max_tokens=6000`.

Schema (`format`):
```json
{"type":"object","required":["contact","summary","sections"],"properties":{
  "contact":{"type":"object","required":["name","email","phone","location","links"],"properties":{
    "name":{"type":"string"},"email":{"type":"string"},"phone":{"type":"string"},
    "location":{"type":"string"},"links":{"type":"array","items":{"type":"string"}}}},
  "summary":{"type":"string"},
  "sections":{"type":"array","items":{"type":"object","required":["heading","kind","entries","items"],"properties":{
    "heading":{"type":"string"},
    "kind":{"type":"string","enum":["summary","experience","education","projects","skills","leadership","awards","certifications","other"]},
    "entries":{"type":"array","items":{"type":"object","required":["title","organisation","location","dates","subtitle","bullets"],"properties":{
      "title":{"type":"string"},"organisation":{"type":"string"},"location":{"type":"string"},
      "dates":{"type":"string"},"subtitle":{"type":"string"},
      "bullets":{"type":"array","items":{"type":"string"}}}}},
    "items":{"type":"array","items":{"type":"string"}}}}}}}
```
Code then assigns entry ids `e1…` and bullet ids `1…` in reading order. A `summary`-kind section's text moves to `MasterResume.summary` (and the section is dropped from `sections`).

### 3.3 Leaf check

`norm(s)`: NFKC; replace `‐‑‒–—―` with `-`, `’‘` with `'`, `“”` with `"`; delete bullet glyphs `•▪◦●‣∙·` and soft hyphens; collapse all whitespace (including newlines) to one space; casefold. The text is checked in two forms: `norm(text)` and `norm(text)` with `(\w)- (\w)` → `\1\2` (PDF line-break hyphenation). Every non-empty leaf (contact fields, links, summary, headings, every entry field, every bullet, every item) must be a substring of one of them. Failures → one retry with the user prompt extended by `THESE STRINGS ARE NOT IN THE RESUME, COPY EXACTLY: <up to 10 failing leaves, truncated to 80 chars>`; still failing → `MasterParseError` (tailoring fails; nothing is cached). Logged: counts only ("master parse: 4 sections, 9 entries, 23 bullets" / "leaf check failed on 3 strings").

---

## 4. JD terms (F-21)

### 4.1 Matcher (`terms.py`; independent of `profile/keywords.py`, which folds variants together on purpose)

- Tokens: `[A-Za-z0-9][A-Za-z0-9+#]*(?:\.[A-Za-z0-9+#]+)*` over the text (so `CI/CD` → `CI` `CD`, `node.js` stays one token).
- Token key: lowercase; `.js` suffix → `js`; a trailing `s` dropped when the token is longer than 3 chars and doesn't end `ss` ("APIs" = "API"). No alias folding.
- A term matches at a position when its token keys equal a contiguous run of text token keys. **Ambiguous** tokens (`aliases.yaml` `ambiguous`, default `go`, `c`, `r`) match only when the text token is not all-lowercase; a lowercase ambiguous token in the text also breaks runs (as in `keywords.py`), so "go-live" never yields "Go".
- `find(text, term) -> list[(start, end)]` returns character spans (first token start to last token end); the **surface** is `text[start:end]`.

### 4.2 Dictionary

`Dictionary` = every `aliases.yaml` canonical, variant and instance + the applicant's `skills` + `attested_skills` + the master's skills items. Each dictionary string resolves to its aliases entry (if any) for `canonical`.

### 4.3 Deterministic extraction

1. JD text = `jobs.jd_text`; if it looks like HTML (`<[a-z][a-z0-9]*[\s>/]`) the orchestrator converts it with `html_to_text`. Truncated to `tailor.max_jd_chars` (12000).
2. Find every dictionary string in the JD. **Overlap rule:** when spans overlap, keep the longest (token count), then the earliest; so "Spring Boot" suppresses "Spring", and "REST APIs" vs its variant "REST API" collapse to one hit.
3. Group hits by canonical; the term's spelling is the surface of its **first** hit.
4. **Required vs preferred:** split the JD into lines; a heading line is ≤ 8 words and either ends with `:` or is in title case with no sentence punctuation. Lines under a heading matching `/nice to have|preferred|bonus|desirable|good to have|a plus|advantage|optional/i`, or lines that themselves contain one of `is a plus|preferred|nice to have|bonus|advantageous`, are *preferred*; everything else is *required*. A term with any required hit is required.
5. **Knockouts:** JD lines matching `/citizen|permanent resident|\bPR\b|work pass|employment pass|visa|sponsorship|right to work|must be (based|located) in|security clearance/i` (trimmed, ≤ 200 chars, at most 5) go to `TailorResult.knockouts` (shown as "Application questions to expect"; never resume content).

### 4.4 LLM extraction (M21; one call, temperature 0)

System: `List the skills, tools, technologies, qualifications and practices this job asks for, copying each term exactly as the job description spells it. Put must-haves in "required" and nice-to-haves in "preferred". Use at most 4 words per term. List acronym pairs written in the text, like "machine learning (ML)", as [short, long].` User: `JOB TITLE: <title>\n\n<jd text>`. Schema: `{"type":"object","required":["required","preferred","acronym_pairs"],"properties":{"required":{"type":"array","items":{"type":"string","maxLength":60},"maxItems":25},"preferred":{"type":"array","items":{"type":"string","maxLength":60},"maxItems":15},"acronym_pairs":{"type":"array","items":{"type":"array","items":{"type":"string"},"minItems":2,"maxItems":2},"maxItems":10}}}`.

Filter: keep a term only if `find(jd, term)` is non-empty (**occurs in the JD**, F-21) and it has ≤ 4 tokens and is not in the stop list (`experience`, `skills`, `ability`, `knowledge`, `degree`, `team`, `communication` alone, `work`, `years`). Spelling = its first JD surface. An acronym pair is kept only if both members occur in the JD; it then acts as a run-time alias (`via = "acronym"`).

**Merge:** union with §4.3 by canonical (an LLM term with no aliases entry has canonical = its lowercase); a term from both sources gets `source = "both"`; required/preferred: the LLM's label wins for LLM terms, §4.3 step 4 for dictionary-only terms. `BackendError` or unreadable JSON → deterministic terms only (logged "jd terms: model unavailable, dictionary only").

---

## 5. Mapping and coverage (F-21)

### 5.1 Classification of each term against the master (`mapping.classify`)

Resume text for mapping = the master's leaves joined (contact excluded): summary, all entry fields, bullets, items.

1. `PRESENT_EXACT` if `find(resume_text, term)` hits.
2. else `PRESENT_VARIANT` if any alias variant (or the canonical, when the JD used a variant) hits: `variant` = that resume surface, `via = "alias"`; or a run-time acronym pair member hits (`via = "acronym"`); or an `instances` entry of the term hits (`via = "instance"`).
3. else `MISSING`; `related` = a dictionary term found in the resume whose tokens are a strict contiguous sub-run of the term's tokens (resume "Spring" → JD "Spring Boot"), else "".
4. `attested = True` when the canonical is in `applicant.attested_skills` (normalised); an attested missing term is rendered in the skills list (§6.3) and so counts after tailoring.

The model never decides that the resume "implies" a term (brief §5B).

### 5.2 Coverage (`mapping.coverage(terms, text) -> float`)

`coverage = Σ weight(t) for t whose JD spelling hits text  /  Σ weight(t) for all t`, weights 2 (required) and 1 (preferred) (F-21); 0 when there are no terms. **Before** is computed on the master's resume text; **after** on the rendered DOCX's extracted text. Only the JD spelling counts (a variant does not). Displayed as a whole percent, labelled "JD keyword coverage" — never "ATS score". `title_match` = the headline equals `jobs.title`.

---

## 6. Deterministic rewrite (M20)

### 6.1 `config/aliases.yaml` format (researcher fills content; public, generic)

```yaml
version: 1
ambiguous: [go, c, r]          # tokens that match only when capitalised in the text
terms:
  - canonical: PostgreSQL      # the preferred spelling
    variants: [Postgres, psql] # TRUE synonyms only: swapping one for the other never changes the claim
    kind: tool                 # tool | language | framework | platform | practice | domain | soft
  - canonical: Kubernetes
    variants: [k8s]
  - canonical: machine learning
    variants: [ML]
  - canonical: REST APIs
    variants: [REST API, RESTful APIs, REST endpoints]
  - canonical: CI/CD
    variants: [continuous integration]
    instances: []              # curated "instance of" claims (brief D7), e.g. [GitHub Actions]; each is a deliberate truth claim
  - canonical: Go
    variants: [Golang]
```
Rules the loader enforces: a string appears in at most one entry (as canonical, variant or instance) → else `AliasError` naming both; canonicals unique by token key; `kind` from the list. `aliases_hash` = SHA-256 of the file bytes (part of the inputs hash, §11.2).

### 6.2 Variant swap (`rewrite.swap`)

For each `PRESENT_VARIANT` term with `via` `alias` or `acronym`, in every bullet, the summary and the skills items (**never** in entry titles, organisations, locations, dates, subtitles, headings or contact):

- replace each occurrence (by §4.1 spans) of `variant` with the JD spelling `term`;
- **acronym direction:** if `term` is an acronym (≤ 5 chars, no lowercase letters) and `variant` is the long form, the **first** occurrence in the document becomes `"<variant> (<term>)"` and later ones `term`;
- **article fix:** if the word before the replaced span is `a`/`an`/`A`/`An`, set it from the new text: an acronym (no lowercase) starting with `A E F H I L M N O R S X` → `an`, any other acronym → `a`; otherwise first letter in `aeiou` → `an`, else `a` (case of the article preserved);
- skills item equal (case-insensitive) to the variant → the JD spelling; duplicates removed keeping the first.

For `via = "instance"`: no replacement; the first occurrence of the instance gets `" (<term>)"` appended ("GitHub Actions (CI/CD)").

Each changed bullet records a `BulletChange(source="swap")`.

### 6.3 Skills list and reorder

- **Skills order:** required terms present after swaps in JD order, then preferred present in JD order, then the remaining items in master order; then attested missing JD terms (JD spelling) appended. Items only ever come from the master items (after swaps) and attested skills (validator §8.3).
- **Bullet order (deterministic, M20):** within each entry, stable sort by descending score = Σ weights of JD terms whose spelling hits the bullet after swaps. Entries and sections keep master order. (M21: the model's order for rewritable entries, §7.)
- **Headline** (D-60, `tailor.headline: true`): `jobs.title` verbatim, as a line under the name.

---

## 7. LLM entry rewrite (M21; after spike S-2)

### 7.1 Scope

One call per entry in a section of kind `experience`, `projects` or `leadership` (`REWRITABLE_KINDS`) with ≥ 1 bullet. Input bullets are the post-swap texts. Education, skills, awards, contact and every protected field are never sent.

### 7.2 Prompt

System (`rewrite.ENTRY_SYSTEM`):
```
You improve the bullet points of ONE resume entry for a specific job, without changing what they claim.
Allowed: reword a bullet to surface one of the ALLOWED TERMS that the bullet already supports; tighten wording;
reorder the bullets so the most relevant to the job comes first.
Not allowed: adding or removing any number; adding any tool, technology, skill, company, product or
certification that is not already in that same bullet; moving content between bullets; upgrading a claim
("used" -> "led", "Spring" -> "Spring Boot"); dropping a bullet; merging bullets.
Example of a violation: "Built dashboards in Tableau" -> "Built dashboards in Power BI and Tableau" (adds a tool).
Correct: "Built dashboards in Tableau" -> "Built Tableau dashboards" .
Return every id exactly once, most relevant first. "keywords_used" lists the ALLOWED TERMS you used.
```
User: `JOB: <title>\nALLOWED TERMS (this entry already supports them): <comma list>\nBULLETS:\n[{"id": 3, "text": "…"}, …]`. ALLOWED TERMS = JD terms (present_exact/variant, JD spelling) whose spelling or variant hits this entry's bullets — computed by code.

Schema: `{"type":"object","required":["bullets"],"properties":{"bullets":{"type":"array","minItems":n,"maxItems":n,"items":{"type":"object","required":["id","text","keywords_used"],"properties":{"id":{"type":"integer","enum":[<ids>]},"text":{"type":"string","minLength":1,"maxLength":<ceil(1.4 × longest)>},"keywords_used":{"type":"array","items":{"type":"string"},"maxItems":5}}}}}}`.

Options: `temperature=0.25` (D-60), `top_k=20`, `seed=7`, `max_tokens = 120 × n + 200`. Backend change: `format`/`temperature`/`seed`/`top_k` per call (`apply_design.md` §7.6).

### 7.3 Handling

Per bullet: validator §8.1. Failing bullets get **one** retry: a second call with only the failing bullets and the user prompt extended by `THESE REWRITES BROKE THE RULES: [{"id": 3, "problems": ["added number 12"]}]` (problems from the issue codes; no other text). A bullet failing again → the post-swap text (`source = "fallback"`, issues kept). Id-level failures (missing/unknown/duplicate ids, unreadable JSON, `BackendError`) → the whole entry falls back (`MODEL_ERROR`), no retry beyond one. The model's order is used for bullets that passed; fallback bullets keep their deterministic position relative to each other and are placed after passing bullets of equal deterministic score.

---

## 8. Validator (F-22)

### 8.1 Bullet check `validate.bullet(src, out, ctx) -> list[ValidationIssue]` (all deterministic)

- **Ids** (entry level): output ids = input ids, each once (`ID_MISSING`, `ID_UNKNOWN`, `ID_DUPLICATE`).
- **Empty:** stripped output empty → `EMPTY`.
- **Numbers:** multiset of `\d+(?:[.,]\d+)*(?:%|[kKmMbB]\b|x\b)?` (commas inside digit groups removed; no left boundary, so "p95" yields 95; "S$1.2M" yields "1.2M") must be equal: extra → `NUMBER_ADDED`, missing → `NUMBER_DROPPED`.
- **Fact tokens** `facts(text)` = canonicals of dictionary hits (§4.1/§4.2, longest-match) ∪ acronyms (tokens of ≥ 2 chars, not starting with a digit, with no lowercase letters and at least one letter) ∪ capitalised words not at sentence start (lowercased), minus a stop list (`I`, month and weekday names). Acronyms and capitalised words are taken **only from tokens outside every dictionary-hit span** (so "ML" counts once, as "machine learning", and "REST" inside "REST APIs" is not a second fact). Compare after mapping each through the alias table (so "Postgres" ≡ "PostgreSQL"): `facts(out) − facts(src)` non-empty → `FACT_ADDED` (attested terms are **not** exempt in bullets: an attested skill goes only into the skills list and summary); `facts(src) − facts(out)` non-empty → `FACT_DROPPED`.
- **Keywords:** each `keywords_used` entry must hit `out` and its canonical must be in `facts(src)` → else `KEYWORD_UNSUPPORTED`.
- **Length:** `0.6 × len(src) ≤ len(out) ≤ 1.4 × len(src)` → else `LENGTH`.

The deterministic swap output is validated the same way (it passes by construction; this guards bugs).

### 8.2 Summary check (§9)

Numbers in the new summary ⊆ numbers anywhere in the master; facts ⊆ facts(master) ∪ attested canonicals; no organisation, title or institution string that isn't in the master; length ≤ max(1.4 × original, 80 words). Fail (after one retry) → the post-swap original summary.

### 8.3 Resume-wide invariants (run on the final document model before rendering, and the oracle for golden tests)

- For every entry: title, organisation, location, dates, subtitle byte-equal to the master.
- Section headings, entry ids and order equal to the master (bullets may be reordered or trimmed, never moved across entries).
- Every kept bullet passed §8.1 or is its master/post-swap text.
- Skills items ⊆ (master items after swaps) ∪ attested JD terms.
- Contact block byte-equal to the master.
Violation → tailoring fails (`error = "invariant: <which>"`), never a silent fix.

---

## 9. Summary rewrite (M21)

Only when the master has a summary. One call, temperature 0.25, `top_k=20`, `seed=7`, `max_tokens=300`.
System: `Rewrite this resume summary for the job below in at most 60 words, first person implied (no "I"). Use only skills and facts present in SKILLS and the ORIGINAL summary. Prefer the job's spelling of terms in TERMS. Add no numbers, employers or skills.` User: `JOB: <title>\nTERMS: <JD spellings of present terms, required first>\nSKILLS: <skills after swaps + attested>\nORIGINAL: <post-swap summary>`. Schema `{"type":"object","required":["summary"],"properties":{"summary":{"type":"string","minLength":20,"maxLength":600}}}`. Validator §8.2, one retry, then fallback.

---

## 10. Output: DOCX template, PDF, round trip (F-23)

### 10.1 Template (built in code with python-docx; `render.TEMPLATE_VERSION = 1`)

- `docx.Document()`; one section, A4 (21.0 × 29.7 cm), margins 1.8 cm; **no** text in headers or footers, no tables, text boxes, images, columns, fields or hyperlink fields (links as plain text).
- Fonts: `Normal` = Calibri 10.5 pt, line spacing 1.0, space after 0. Name: paragraph with one run, Calibri 18 pt bold. Headline (if on): Calibri 11 pt. Contact line: one paragraph `email | phone | location | link1 | link2` (non-empty parts).
- Section headings: built-in style `Heading 1`, restyled Calibri 11.5 pt bold, black, space before 8 pt, after 2 pt. Text from the kind: SUMMARY "Summary", EXPERIENCE "Experience", EDUCATION "Education", PROJECTS "Projects", SKILLS "Skills", LEADERSHIP "Leadership", AWARDS "Awards", CERTIFICATIONS "Certifications", OTHER = the master heading verbatim.
- Entry header: one paragraph, space before 4 pt: bold run `title`, then `, organisation` (if any), then ` — location` (if any), then a tab and `dates`, with a right-aligned tab stop at the text width (17.4 cm). Subtitle (if any): its own paragraph, italic.
- Bullets: built-in style `List Bullet`, one paragraph per bullet, plain runs.
- Skills: one paragraph `item1, item2, …` (no table, no columns). Other `items` sections: one `List Bullet` per item.
- Summary: one paragraph after the contact line under "Summary".
- Order: name, headline, contact line, Summary, then master section order.
- Document core properties: title = "Resume", author = the applicant's name; no comments, no tracked changes.

**File name** (F-23): `<First>_<Last>_Resume.docx|pdf` from `applicant.identity.legal_first_name/last_name` (fallback: master contact name split on the first space), each reduced to `[A-Za-z0-9-]` (other characters removed; empty → `Resume.docx`). Written under `data/tailored/<job_id>/` (job id sanitised to `[A-Za-z0-9_-]`).

### 10.2 Page ceiling (D-60)

Ceiling = `tailor.page_ceiling` (`auto` = `master.page_count`). After rendering, page count via Word (§10.3). Over the ceiling → drop one bullet: among entries with > 2 kept bullets, the bullet with the lowest relevance score (§6.3), ties → the last bullet of the last such entry; record `BulletChange(source="trimmed")` + `PAGE_TRIM` issue; re-render; at most 10 rounds; still over → keep and record `PAGE_TRIM` with detail "still over". Without Word the ceiling is not enforced (issue `PDF_UNAVAILABLE`, detail "page count unknown").

### 10.3 PDF through Word (pywin32, optional dependency)

In a worker thread with `pythoncom.CoInitialize()`, 90 s timeout: `word = win32com.client.DispatchEx("Word.Application")`, `word.Visible = False`, `word.DisplayAlerts = 0`, `doc = word.Documents.Open(abs_docx, ReadOnly=True, AddToRecentFiles=False)`, `pages = doc.ComputeStatistics(2)` (wdStatisticPages), `doc.ExportAsFixedFormat(abs_pdf, 17)` (wdExportFormatPDF), `doc.Close(False)`, `word.Quit()` in `finally`. `ImportError` or any COM error → no PDF, issue `PDF_UNAVAILABLE`; tailoring still succeeds with the DOCX (`tailor.pdf: false` skips the attempt).

### 10.4 Round-trip check

Re-extract each produced file with the injected `extract_text` (the app's own extractor: `_docx_text` for DOCX, pypdf for PDF), `norm` (§3.3). Must find, **in this order**: the name; each rendered section heading; and, within the text, every entry's organisation and dates string (each at least once). Any miss → tailoring fails (`ROUNDTRIP` issue with the missing item's kind, e.g. "dates of e3"), files deleted, row `failed`. The PDF failing alone → PDF deleted, `PDF_UNAVAILABLE` + `ROUNDTRIP` issues, DOCX kept.

---

## 11. Storage and retention (F-24, D-59)

### 11.1 `tailored` table (store, `SCHEMA_VERSION` 3 together with the apply tables)

```sql
CREATE TABLE IF NOT EXISTS tailored (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,             -- §11.2
    resume_hash TEXT NOT NULL, jd_hash TEXT NOT NULL,
    mode TEXT NOT NULL,                    -- deterministic | llm
    model TEXT, options_json TEXT,         -- {"temperature":0.25,"top_k":20,"seed":7,"template":1}
    status TEXT NOT NULL CHECK (status IN ('draft', 'sent', 'failed')),
    created_at TEXT NOT NULL, sent_at TEXT, files_deleted_at TEXT,
    docx_name TEXT, docx_sha256 TEXT, pdf_name TEXT, pdf_sha256 TEXT,
    coverage_before REAL, coverage_after REAL, title_match INTEGER,
    terms_json TEXT,                       -- [{term, canonical, required, source, status, variant, via, related, attested}]
    knockouts_json TEXT,
    changes_json TEXT,                     -- BulletChange list + summary before/after; cleared when files are purged
    issues_json TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_tailored_job ON tailored(job_id, id);
```
Store methods: `add_tailored(row) -> int`, `latest_tailored(job_id)`, `current_tailored(job_id, inputs_hash)`, `mark_tailored_sent(id, now)`, `tailored_to_purge(now, draft_days, sent_days, closed_statuses) -> list[row]`, `mark_tailored_purged(id, now)` (sets `files_deleted_at`, clears `changes_json`).

### 11.2 "Current" tailored file

`inputs_hash = sha256(json.dumps([resume_hash, jd_hash, aliases_hash, sorted(attested canonicals), render.TEMPLATE_VERSION, mode, headline flag]))`, `jd_hash = sha256(jd text used)`. Current = the newest row for the job with that `inputs_hash`, status `draft` or `sent`, `files_deleted_at IS NULL`, and its DOCX on disk with a matching SHA-256. `tailor_for_apply` reuses it; `tailor` creates a new row unless `force` is false and a current one exists (then it returns it).

### 11.3 Retention (`storage.purge`, run from `cmd_purge` and where the run calls `purge_descriptions`)

- `draft` rows with `created_at` older than `tailor.draft_days` (7) → delete the files and the job's directory if empty; `mark_tailored_purged`.
- `sent` rows whose job's application is in `tailor.closed_statuses` (default `[rejected, withdrawn]`) with the latest transition to that status (from `app_events`) older than `tailor.sent_days_after_close` (30) → same.
- `failed` rows: files deleted when the row is written.
- Rows are never deleted (scores, terms, hashes stay; F-24).
- `mark_tailored_sent` is called by `apply_flow` on `submitted` (and on the owner's "It went through"), and by the web "Mark applied" action for the job's current draft (M21).

### 11.4 Privacy

`.gitignore` already covers `data/master_resume.json` and `data/tailored/` (verified on `personal`). Job logs carry counts and ids only (§19).

---

## 12. Hand-off to auto-apply (F-25 bullet 2, D-58)

`apply_flow` in `tailoring` calls `tailor_for_apply`. Result `ok` → upload `pdf_path` if `apply.resume_format == "pdf"` and it exists, else `docx_path`; record `resume_source = tailored`, `tailored_id`, file name and SHA-256 on the attempt. Not ok → the original resume (`find_resume`), `resume_source = original`, the tailor error in the job log. No review gate (D-58); the diff stays viewable.

---

## 13. Interfaces

### 13.1 CLI

`tailor <job_id> [--report] [--force]`:
- `--report`: steps through coverage before (no swaps, no files, no DB row); prints `term | required/preferred | status | variant/related` and "JD keyword coverage: NN%"; exit 0. This is the M20 skeleton check.
- default: full tailoring; prints coverage before → after, counts (changed / fallback / trimmed bullets), missing terms, file names (not paths with the user name: `data/tailored/<job_id>/<file>`); exit 0 on success, 1 on failure (message = error).

`purge` (existing) also purges tailored files and prints `tailored files deleted: N`.

### 13.2 Job kind

`web/jobs.py`: kind `tailor`, opts `{job_id}` → argv `["tailor", job_id]` (validated `^[A-Za-z0-9:_-]{1,80}$`).

### 13.3 Web API (M21; router `web/routers/tailor.py`)

| Method, path | Request | Response |
|---|---|---|
| `POST /api/tailor` | `{job_id}` | 202 `{job}`; 409 busy; 404 unknown job |
| `GET /api/tailor/{job_id}` | | 200 latest row: `{id, status, mode, created_at, current, coverage_before, coverage_after, title_match, terms:[…], missing:[term…], related:[{term, related}], knockouts:[…], changes:[{entry_id, entry_title, before, after, source, issues:[{code, detail}]}], summary:{before, after}, files:{docx, pdf} (names or null), files_deleted_at, error}`; 404 none |
| `GET /api/tailor/file/{tailored_id}/{kind}` | kind `docx`\|`pdf` | the file, `Content-Disposition: attachment; filename="<First>_<Last>_Resume.<ext>"`; 404 if purged |
| `POST /api/tailor/attest` | `{term}` | 200 `{attested_skills}`: appends the JD spelling to `data/applicant.yaml` `attested_skills` via `applicant.save` (dedupe by normalised text) |

`entry_title` is the entry's title + organisation (for the diff headers).

### 13.4 UI panel (fast track; Inbox and Applications detail)

- Button **Tailor resume** (secondary) next to Auto-apply; while the job runs: "Tailoring your resume… (about a minute)".
- Result panel:
  - Headline metric: **"JD keyword coverage: 29% → 64%"** with help text "Share of this job's key terms, in its own spelling, found in your resume. Not an ATS score."
  - **Missing terms** chips; each has "I have this" → confirm "Add "<term>" to your skills? It will appear in your skills list on future resumes. Only add it if it's true." [Add to my skills] [Cancel] → POST attest → prompt "Tailor again" button.
  - **Possibly related:** "You have Spring. The job says Spring Boot." with "I have Spring Boot" (same attest flow).
  - **Application questions to expect:** knockout lines.
  - **Changes:** per entry, two columns Before / After with changed words highlighted (word-level diff in the browser); trimmed bullets struck through; fallback bullets labelled "Kept original: <issue text>" (issue code → short text: number_added "it added a number", number_dropped "it dropped a number", fact_added "it added a tool or skill", fact_dropped "it dropped a tool or skill", keyword_unsupported "it used a term the bullet doesn't support", length "it changed the length too much", model_error "the AI step failed").
  - **Download** DOCX / PDF; status line "Draft, deleted after 7 days" / "Sent with your application on <date>" / "Files deleted on <date>".

---

## 14. Config: the `tailor:` block (engineer adds to `config/config.yaml`)

```yaml
tailor:
  enabled: true
  llm: false                 # M20: deterministic only. M21: true after spike S-2
  temperature: 0.25          # D-60
  top_k: 20
  seed: 7
  headline: true             # D-60: the job title as a headline under your name
  pdf: true                  # through Word, when installed
  page_ceiling: auto         # auto = your resume's page count, or a number
  max_jd_chars: 12000
  draft_days: 7              # D-59
  sent_days_after_close: 30  # D-59
  closed_statuses: [rejected, withdrawn]
paths:
  aliases: config/aliases.yaml
  master_resume: data/master_resume.json
  tailored_dir: data/tailored
```
`config.py` gains `Config.tailor` (frozen `TailorConfig`) and the three paths.

---

## 15. Golden cases (oracles for the tester; synthetic, no real person)

Fixtures (tester writes them from this section): `tests/fixtures/tailor/aliases_golden.yaml`, three masters as JSON (`master_a.json` …), three JD texts, and the expected outputs below. Golden tests use these fixtures, **not** `config/aliases.yaml`, and mock the backend (deterministic mode needs none).

`aliases_golden.yaml`:
```yaml
version: 1
ambiguous: [go, c, r]
terms:
  - {canonical: PostgreSQL, variants: [Postgres], kind: tool}
  - {canonical: Kubernetes, variants: [k8s], kind: platform}
  - {canonical: machine learning, variants: [ML], kind: domain}
  - {canonical: REST APIs, variants: [REST API, REST endpoints], kind: practice}
  - {canonical: CI/CD, variants: [], kind: practice}
  - {canonical: Go, variants: [Golang], kind: language}
  - {canonical: Kafka, variants: [], kind: tool}
  - {canonical: Python, variants: [], kind: language}
  - {canonical: Git, variants: [], kind: tool}
  - {canonical: GitHub Actions, variants: [], kind: tool}
  - {canonical: SQL, variants: [], kind: language}
  - {canonical: Power BI, variants: [], kind: tool}
  - {canonical: Excel, variants: [MS Excel], kind: tool}
  - {canonical: Tableau, variants: [], kind: tool}
  - {canonical: pandas, variants: [], kind: tool}
  - {canonical: A/B testing, variants: [], kind: practice}
  - {canonical: stakeholder management, variants: [], kind: soft}
  - {canonical: Java, variants: [], kind: language}
  - {canonical: Spring, variants: [], kind: framework}
  - {canonical: Spring Boot, variants: [], kind: framework}
  - {canonical: microservices, variants: [], kind: practice}
  - {canonical: RabbitMQ, variants: [], kind: tool}
  - {canonical: AML, variants: [], kind: domain}
  - {canonical: KYC, variants: [], kind: domain}
  - {canonical: Docker, variants: [], kind: tool}
```
Applicant fixture: `skills: []`, `attested_skills: []`; `tailor.headline: true`.

### Case A — new-grad backend (variant mirroring)

Master A: contact name "Jane Tan"; Education → entry e1 {title "B.Eng. Computer Engineering", organisation "Nanyang Example University", dates "2025"}; Experience → entry e2 {title "Software Engineering Intern", organisation "Acme Logistics Pte Ltd", dates "May 2024 – Aug 2024", bullets 1 "Built REST APIs in Python and Postgres for shipment tracking.", 2 "Deployed services on k8s with GitHub Actions; cut p95 latency 35%.", 3 "Trained an ML model to predict delivery delays (82% accuracy)."}; Skills items [Python, Postgres, k8s, GitHub Actions, ML, Git].
JD A (title "Backend Engineer (Graduate)"):
```
Backend Engineer (Graduate)
Requirements:
- Python and PostgreSQL
- Kubernetes
- REST APIs
- CI/CD
- Go
Nice to have:
- machine learning
- Kafka
```
Expected:
- Terms (JD order): required Python, PostgreSQL, Kubernetes, REST APIs, CI/CD, Go; preferred machine learning, Kafka.
- present_exact {Python, REST APIs}; present_variant {PostgreSQL←Postgres, Kubernetes←k8s, machine learning←ML} (via alias); missing {CI/CD, Go, Kafka}, all with `related = ""`.
- Coverage before 4/14 = 0.2857 (29%); after 9/14 = 0.6429 (64%); `title_match` true.
- After (deterministic): bullet 1 "Built REST APIs in Python and PostgreSQL for shipment tracking."; bullet 2 "Deployed services on Kubernetes with GitHub Actions; cut p95 latency 35%."; bullet 3 "Trained a machine learning model to predict delivery delays (82% accuracy)." (article fix). Bullet order unchanged (scores 6, 2, 1). Skills [Python, PostgreSQL, Kubernetes, machine learning, GitHub Actions, Git].
- Absent everywhere in the output text: "Go", "Kafka", "CI/CD".
- Invariants: e1/e2 protected fields byte-equal; numbers per bullet {95, 35%} and {82%} unchanged.

### Case B — data analyst (no tool swapping)

Master B: "Wei Ling Lim"; Experience e1 {title "Business Analyst Intern", organisation "Example Bank", dates "Jan 2025 – Jun 2025", bullets 1 "Automated 40 weekly reports with SQL and Python (pandas).", 2 "Built Tableau dashboards tracking S$1.2M in card spend.", 3 "Analysed pivot tables in Microsoft Excel for the ops team."}; Skills [SQL, Python, pandas, Tableau, Excel].
JD B (title "Data Analyst"):
```
Data Analyst
Requirements:
- SQL and Power BI
- Excel
- stakeholder management
Nice to have:
- A/B testing
- Python
```
Expected:
- Required SQL, Power BI, Excel, stakeholder management; preferred A/B testing, Python.
- present_exact {SQL, Excel, Python}; present_variant {}; missing {Power BI, stakeholder management, A/B testing}.
- **Deviation from the brief:** the brief lists Excel as a variant of "Microsoft Excel"; by the matcher the JD spelling "Excel" occurs inside "Microsoft Excel", so it is present_exact and nothing is swapped (no swap is needed for coverage, and "Microsoft Excel" stays as written).
- Coverage before 5/10 = 0.50; after 0.50 (no change; after ≥ before holds).
- After: bullets unchanged; order by score: bullet 1 (SQL 2 + Python 1 = 3), bullet 3 (Excel 2), bullet 2 (0) → [1, 3, 2]. Skills [SQL, Excel, Python, pandas, Tableau].
- Absent everywhere: "Power BI", "stakeholder management", "A/B testing". "Tableau" stays in bullet 2; "for the ops team" stays.
- Invariants: Example Bank; Business Analyst Intern; Jan 2025 – Jun 2025; numbers {40}, {1.2M}.

### Case C — fintech Java (no upgrading a claim)

Master C: "Arjun Nair"; Experience e1 {title "Software Engineer", organisation "Example Pay Pte Ltd", dates "Jul 2023 – present", bullets 1 "Developed payment microservices in Java and Spring, exposing REST endpoints.", 2 "Integrated RabbitMQ message queues; processed 2M transactions/day.", 3 "Wrote KYC document checks reducing manual review by 30%."}; Education e2 {title "BSc Computer Science", dates "2023"}; no skills section.
JD C (title "Backend Engineer, Payments"):
```
Backend Engineer, Payments
Requirements:
- Java, Spring Boot, REST APIs
- Kafka and microservices
- Must be a Singapore Citizen/PR
Nice to have:
- AML/KYC
- Docker
```
Expected:
- Required Java, Spring Boot, REST APIs, Kafka, microservices; preferred AML, KYC, Docker. ("Spring" is suppressed in the JD by the overlap rule.)
- present_exact {Java, microservices, KYC}; present_variant {REST APIs←REST endpoints}; missing {Spring Boot (related "Spring"), Kafka, AML, Docker}.
- Knockouts: ["- Must be a Singapore Citizen/PR"].
- Coverage before 5/13 = 0.3846 (38%); after 7/13 = 0.5385 (54%).
- After: bullet 1 "Developed payment microservices in Java and Spring, exposing REST APIs."; bullets 2, 3 unchanged; order by score [1 (Java 2 + microservices 2 + REST APIs 2), 3 (KYC 1), 2 (0)].
- Absent everywhere: "Spring Boot", "Kafka", "Docker", "AML". "RabbitMQ" stays; "present" stays.
- Invariants: Example Pay Pte Ltd; Software Engineer; Jul 2023 – present; BSc Computer Science; 2023; numbers {2M}, {30%}.

### Validator rejections (4 per case; each must yield exactly the listed issues, and the output keeps the post-swap bullet)

| Case | Bullet | Bad rewrite | Issues |
|---|---|---|---|
| A | 2 | "Deployed 12 services on Kubernetes with GitHub Actions; cut p95 latency 35%." | NUMBER_ADDED "12" |
| A | 3 | "Trained a machine learning model to predict delivery delays." | NUMBER_DROPPED "82%" |
| A | 2 | "Deployed services on Kubernetes with Jenkins; cut p95 latency 35%." | FACT_ADDED "jenkins", FACT_DROPPED "github actions" |
| A | 1 | "Built REST APIs in Python and PostgreSQL with Git for shipment tracking." | FACT_ADDED "git" |
| B | 1 | "Automated 40 weekly reports with SQL and Python (pandas), saving 10 hours." | NUMBER_ADDED "10" |
| B | 2 | "Built Tableau dashboards tracking card spend." | NUMBER_DROPPED "1.2M" |
| B | 2 | "Built Power BI dashboards tracking S$1.2M in card spend." | FACT_ADDED "power bi", FACT_DROPPED "tableau" |
| B | 3 | "Analysed pivot tables in Microsoft Excel with SQL for the ops team." | FACT_ADDED "sql" |
| C | 1 | "Developed 5 payment microservices in Java and Spring, exposing REST APIs." | NUMBER_ADDED "5" |
| C | 2 | "Integrated RabbitMQ message queues processing transactions daily." | NUMBER_DROPPED "2M" |
| C | 2 | "Integrated Kafka message queues; processed 2M transactions/day." | FACT_ADDED "kafka", FACT_DROPPED "rabbitmq" |
| C | 1 | "Developed payment microservices in Java and Spring Boot, exposing REST APIs." | FACT_ADDED "spring boot", FACT_DROPPED "spring" |

(Fact details are canonicals lowercased. "REST APIs" vs "REST endpoints" is alias-equal and raises nothing. Length issues are not expected in these rows.)

### Also

- LLM-extraction filter oracle: mock the model to return the true terms plus "Terraform"; "Terraform" must be dropped (not in the JD).
- The rendered DOCX of each case passes the round trip (§10.4) and has no tables, headers, footers or text boxes (inspect `word/document.xml` and the absence of `w:tbl`, `w:txbxContent`, header text).

---

## 16. Requirement map

| Req | Where |
|---|---|
| F-20 | §3 (parse, leaf check, cache by hash) |
| F-21 | §4 (dictionary + LLM with occurs-in-JD filter), §5 (classification, coverage, naming) |
| F-22 | §6 (swaps, aliases.yaml), §7 (per-entry LLM, temperature 0.25, schema), §8 (validator, fallback), §9 (summary), §5.1 + §13.3 attest ("I have this"); protected fields §3, §8.3 |
| F-23 | §10 (template, Word PDF, page ceiling, round trip, file naming) |
| F-24 | §11 (table, paths, D-59 retention in purge, privacy), §19 |
| F-25 | §12 (auto-tailor on apply), §13 (CLI, job, API, UI panel) |
| NF-01 | §11.4 (paths gitignored; tester's check-ignore test lists them) |
| NF-03 | §7, §9 (Ollama only) |
| NF-04 | §2 |
| NF-07 | §18 note: deterministic ≤ 10 s; LLM mode budget ≤ 90 s measured in S-2 |

---

## 17. Extension notes

- **New synonym or tool:** add to `config/aliases.yaml` (researcher or owner); no code change; the inputs hash makes old drafts stale.
- **New section kind:** contract change (SectionKind) → architect.
- **Another output layout:** a new `render` template version (`TEMPLATE_VERSION` bump); the round trip stays mandatory.
- **In-place DOCX editing** (brief "later"): a second renderer behind `tailor.layout: template | inplace`; out of scope for M21.
- **Advisory LLM judge** (brief §4.2.4): may only add review flags to `issues`; it can never approve a bullet the validator rejected.

---

## 18. Lanes

**M20 lane T (deterministic tailor)** — branch `eng/M20-T-tailor`, files: `src/jobscraper/tailor/{__init__.py, master.py, terms.py, mapping.py, rewrite.py (swaps, skills/bullet order only), validate.py (§8.1 + §8.3; it guards the swaps), render.py, storage.py}`, `src/jobscraper/tailor_flow.py`, `src/jobscraper/store.py` (one appended block: `tailored` + methods), `src/jobscraper/config.py` (TailorConfig block), `config/config.yaml` (`tailor:` block), `requirements.txt` (`pywin32` marked optional), `cli.py` (one `tailor` verb block + one line in `cmd_purge`), `src/jobscraper/pipeline.py` (one call to `tailor.storage.purge` beside `purge_descriptions`), `web/jobs.py` (kind `tailor` — shared with lane B's `apply` kind: each adds one `elif`; Coordinator merges).
Includes the master parse (one cached LLM call per resume hash; the per-job tailoring itself makes no model call). Verify: golden cases A–C deterministic outputs and validator rows (§15) pass; `tailor <job_id> --report` on a real job; a full `tailor <job_id>` produces a DOCX + PDF that pass the round trip in ≤ 10 s.

**M21 lane LLM (after spike S-2):** `tailor/terms.py` (§4.4), `tailor/rewrite.py` (§7, §9), `tailor/validate.py` (§8.2); flips `tailor.llm: true` after S-2's numbers. **M21 lane UI** (shared with the apply UI lane): `web/routers/tailor.py`, Vue panel §13.4, "Mark applied" → `mark_tailored_sent`.

Shared-file protocol as in `apply_design.md` §19.1 (store.py, cli.py, config.py, config.yaml, requirements.txt, web/jobs.py: each lane appends a self-contained block).

---

## 19. Logging

Job log lines: `tailor <job_id>: terms=8 (required 6) exact=2 variant=3 missing=3 coverage 29% -> 64%`, `rewrite: bullets=3 swapped=3 llm=0 fallback=0 trimmed=0`, `files: <First>_<Last>_Resume.docx, .pdf (2 pages)`, `master parse: …` — never resume text, bullet text, summary, contact values or prompts; errors as `type(exc).__name__` + a message that contains no resume text (the engineer builds messages from ids and counts).

---

## 20. Pending items and PRD conflicts

**Pending spikes**
- **S-2** (Qwen3-14B rewrite at 0.25 on A–C + 3 real JDs): until it reports, `tailor.llm: false` (M20 behaviour). If S-2 shows high validator rejection, the fix is prompt wording or retries, never relaxing §8.
- Word on the owner's PC is assumed (PRD constraints); without it the PDF and the page ceiling are skipped with an issue, not an error.

**PRD conflicts raised (not resolved here)**
1. **Attested skills location (F-22):** the PRD says "save it as an attested skill (profile overrides)", i.e. `config/profile.overrides.yaml`. That file is owner-protected (no agent writes it), hand-edited with comments (a programmatic save would strip them), lives in `config/` (read-only in Docker), and its skills feed the match filter's profile (changing it re-keys prefilter verdicts). This design stores them in `data/applicant.yaml` → `attested_skills` (written by the app, gitignored, edited in the Profile form). Coordinator to confirm or direct otherwise.
2. **Golden case B:** the brief lists Excel as `present_variant`; this design's matcher makes it `present_exact` (the JD spelling occurs inside "Microsoft Excel"). A deliberate oracle change; the reasoning is in §15.
3. **Weights:** the brief multiplied by a multi-word weight; F-21 states required 2 / preferred 1 only. This design follows F-21.
4. **Review gate:** the brief recommended a human diff review before use; D-58 (decided) removed it. Followed D-58.

**Requests**
- Researcher: `config/aliases.yaml` per §6.1 (true synonyms only; instances only as deliberate claims; include the golden terms at minimum).
- Tester: golden fixtures and oracles §15; layering changes (apply design §2.3); NF-01 check-ignore list.
