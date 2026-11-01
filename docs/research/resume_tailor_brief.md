# ATS resume tailor: research brief

*Researcher brief, 2026-11-01. It shapes the design and is not a spec. Every
external claim has a URL, and every URL was checked on **2026-11-01** unless a
line says otherwise. Each claim carries a label:*

- **[F]** fact: stated by the source cited, or read in this repository's code.
- **[I]** inference: drawn from facts, and the reasoning is shown.
- **[O]** opinion: the researcher's recommendation or judgement.

*Scope. The owner wants a feature that tailors the uploaded resume to one job
description. The result is stored only temporarily. Its goal is to pass ATS
screening by using the JD's wording and keywords. A future auto-apply feature
will upload the result. JobScraper is a local, single-user Windows app (Python
3.12, FastAPI, Vue 3, SQLite, Qwen3-14B through Ollama). PRD §6 currently lists
"Résumé tailoring or cover letters" as **out of scope, "Not requested"**
(`.claude/prds/jobscraper-v2.prd.md`, line 426) [F], so this feature needs a PRD
change.*

---

## 1. How ATSs actually screen: myth and fact

### 1.1 Vendor by vendor

| ATS | Parses into fields | Auto-reject mechanism (documented) | Match score / ranking | Sources |
|---|---|---|---|---|
| **Workday** | Yes. Parsing supports DOC, DOCX, HTM, HTML, PDF, RTF and TXT; an unsupported format can produce "Low" or "Unable to Score" [F] | Not documented in the pages read | **Candidate Skills Match**: a machine-learning similarity between skills derived from the application and skills on the requisition. Values are Strong/Good/Fair/Low. Required skills weigh more, and missing requisition skills are listed as "Skills Not Found". It ignores how recent the skills are, how long they were used, and total years of experience. It is "scheduled for retirement" [F]. **HiredScore grades A–D**: A = all basic qualifications, most preferred ones, and an average match above a threshold; C = most but not all basic qualifications [F]. In the August 2026 release, basic-qualification matching moved to an LLM that judges each qualification separately, with a "Fit & Gap" view that points into the parsed profile [F, from a search summary; the page was not opened]. | [Skills Match](https://doc.workday.com/admin-guide/en-us/human-capital-management/recruiting/candidates/candidate-skills-match/bmj1604095304483.html), [HiredScore grades](https://doc.workday.com/hiredscore/en-us/workday-hiredscore/recruiter-productivity-/reference--candidate-grades.html), [HiredScore Aug 2026 notes](https://doc.workday.com/hiredscore/en-us/workday-hiredscore/hiredscore-release-notes/2026/august/wednesday--5th-august.html) |
| **Greenhouse** | Yes (recruiters search resumes by keyword) | Rules on **application questions**, set by recruiters [F, from a search snippet of Greenhouse's own blog] | "Greenhouse never uses AI to rate candidates or auto-reject applications." For in-demand roles its AI "automatically suggests search terms" [F, Greenhouse blog, 2025-01-08]. Third-party sites describe an optional "Talent Matching" feature that does not auto-advance or auto-reject [unverified]. | [Greenhouse AI blog](https://my.greenhouse.com/blogs/how-does-greenhouse-use-ai-heres-everything-candidates-need-to-know), [What happens after you apply](https://my.greenhouse.com/blogs/what-really-happens-after-you-apply-for-a-job) |
| **Lever** | Yes | The Help Center says the archive is "commonly used to auto-archive candidates based off of knockout questions in the application form" [F, from a search summary] | None found in documentation | [Lever: Operating the Archive](https://help.lever.co/hc/en-us/articles/20087374094365) |
| **Taleo (Oracle)** | Yes | **Disqualification questions**: single-answer questions that set minimum eligibility. Their answers decide whether a candidate advances or is automatically disqualified [F] | **ACE prescreening**: candidates are scored on required and asset criteria. Those above the threshold get an ACE icon, and the count of requirements and assets met is shown [F]. In legacy Taleo an ACE candidate could be auto-progressed [community post, secondary]. | [Taleo prescreening](https://docs.oracle.com/en/cloud/saas/taleo-enterprise/20b/otfru/prescreening-candidates.html), [Disqualification question](https://docs.oracle.com/en/cloud/saas/taleo-enterprise/23c/otfru/t-createdusqualificationquestioninlibrary.html) |
| **iCIMS** | Yes | Not found | "Candidate Ranking" uses an AI **Role Fit** score that groups candidates into tiers. iCIMS treats it as an Automated Employment Decision Tool and commissioned bias audits in 2022–23 [secondary; iCIMS's own documentation was not confirmed] | [iCIMS Winter 2021 AI release notes](https://community.icims.com/articles/Knowledge/Release-Notes-Winter-Release-2021-iCIMS-Talent-Cloud-AI), [Jobscan on iCIMS](https://www.jobscan.co/blog/icims-ats/) |
| **SAP SuccessFactors** | Yes | Pre-screening questions with **disqualifying answers or a passing score**. Applicants who fail go to "Auto Disqualified" status [F per SAP course and KB; the KB is old] | Not researched | [SAP course: rejection screening questions](https://learning.sap.com/courses/smartrecruiters-for-sap-successfactors-academy/creating-rejection-screening-questions), [SAP KB 2272147](https://userapps.support.sap.com/sap/support/knowledge/en/2272147) |

### 1.2 The "75% auto-rejected" myth

- [F] The figure is attributed to Preptel, a resume-services vendor, around
  2012. No methodology was ever published. This attribution comes only from
  secondary sources
  ([HiringThing](https://blog.hiringthing.com/applicant-tracking-system-myths)),
  and no primary copy was found.
- [F] Enhancv surveyed 25 US recruiters (reported 2025-11-19). 92% said their
  ATS does not auto-reject on formatting, design, missing keywords or a low AI
  match score. The 8% who did auto-reject used it only for roles with very
  specific requirements, and the filters covered work authorisation, licences,
  minimum qualifications and location. Of the recruiters, 44% have fit scores
  available, but most turn them off or treat them as a rough guide. 76% find
  tailoring useful "if not keyword stuffing", and 72% prefer short bullets
  focused on achievements
  ([IT Brief](https://itbrief.co.uk/story/study-reveals-ats-rarely-auto-rejects-cvs-debunks-75-myth)).
  The sample is small and Enhancv sells resume software, so treat this as
  directional.

### 1.3 What this means for the tailor

- [I] No vendor documents an automatic rejection triggered by **resume keywords**.
  The documented auto-rejects all run on **application questions**: knockout,
  disqualification and pre-screening questions. Those are form answers for a
  future auto-apply feature, not resume content.
- [I] Resume keywords do matter in three ways:
  1. **Recruiter keyword search** (Greenhouse explicitly) matches literal
     strings. Exact JD terms help, including both the acronym and the long form.
  2. **Skill and qualification matchers** (Workday Skills Match, HiredScore,
     iCIMS Role Fit, Taleo ACE) rank candidates and show the rank to a human.
     HiredScore now runs an LLM over each qualification against the *parsed
     profile*, which rewards clear, specific evidence over repetition.
  3. **The human skim** after either of the above.
- [I] Parse fidelity comes first. Every matcher works on the parsed profile, and
  Workday documents that a bad format produces "Unable to Score".
- [O] So the tailor should optimise, in order:
  1. a file that parses cleanly;
  2. coverage of the JD's *required* skills in the JD's own spelling, wherever
     the resume truthfully supports them;
  3. the JD's job title in a headline, if the owner allows it;
  4. relevance ordering for the human reader.

  It should **not** push a keyword count upward. Stuffing is the one tactic
  recruiters name as harmful, and an LLM grader is likely to see through it [I].

---

## 2. Format rules that parse safely

The evidence is thin. No ATS or parser vendor publishes a formatting guide that
we found; a search for Textkernel/Sovren guidance returned nothing primary.
Below, rules are grouped by the quality of their evidence.

**Backed by vendor documentation**
- [F] Use a supported file type. Workday lists DOC, DOCX, HTM, HTML, PDF, RTF
  and TXT, and says an unsupported format can make the score fail
  ([Workday](https://doc.workday.com/admin-guide/en-us/human-capital-management/recruiting/candidates/candidate-skills-match/bmj1604095304483.html)).
- [F] A file must contain real text. The app already refuses a resume with no
  extractable text ("is it a scanned image?") (`resume_ingest.py`, `load_resume`).

**Backed by how the file formats work (checkable locally, not ATS-specific)**
- [F] In a DOCX, headers and footers are stored in separate parts
  (`word/header*.xml`), and text boxes sit inside drawing objects. The app's own
  `_docx_text` reads only `doc.paragraphs` and `doc.tables`, so it **misses
  headers, footers and text boxes** (`resume_ingest.py`, lines 100–110).
  [I] Any parser built the same naive way will miss them too, and contact
  details in a header are the classic case.
- [I] Tables and multiple columns change reading order. A table is read row by
  row, and in a PDF the order of text in columns depends on how it was drawn.
  The app's DOCX extractor even appends table text *after* all the paragraphs,
  so a skills table moves to the end.
- [I] A PDF must have a text layer, and its glyphs must map to Unicode.
  Ligatures and icon fonts can extract as junk.

**Common advice with no primary evidence** (third-party blogs such as
[CareerBldr](https://careerbldr.com/blog/resume-parsing-how-it-works/))
- Single column; standard headings ("Experience", "Education", "Skills");
  standard fonts; no graphics or icons; dates in one consistent format.
  Resume-Matcher scores date consistency because "parsers miscount experience
  when date formats are mixed"
  ([ats.py](https://github.com/srbhr/Resume-Matcher/blob/main/apps/backend/app/services/ats.py)).
  That is a design claim, not a measured one.
- DOCX vs PDF: no source compares parse accuracy across vendors. [O] Use DOCX as
  the default upload. Every listed ATS accepts it, it has no layer of drawn
  glyphs, and python-docx is already a dependency.
- File naming: there is no evidence that the filename affects parsing.
  [O] Use `Firstname_Lastname_Resume.docx`. Never put "tailored", a job ID or
  the company name in it, because recruiters see the filename.

**[O] The practical rule:** do not trust any list. Test the output with a
**round-trip check**: re-extract its text with the app's own `extract_text`
(and with `pypdf` for a PDF). Then assert that the contact line, every section
heading, every employer and every date come back once each, in reading order.
Resume-Matcher does the same thing (`services/ats_parse/roundtrip`).

---

## 3. Prior art

| Project | What it does / how it scores | Licence | Verdict |
|---|---|---|---|
| **Resume-Matcher** (srbhr), [repo](https://github.com/srbhr/Resume-Matcher). 29.0k stars, last push 2026-10-30 | FastAPI (Python 3.13+) with a Next.js front end and SQLite. It reaches LLMs through LiteLLM, **including Ollama** for local use [F]. PDFs are rendered with headless Chromium via Playwright [F]. **Score** (`services/ats.py`): fully deterministic. Weights: keyword match 0.40, skills coverage 0.20, title match 0.15 (exact title in the headline = 100, in the summary = 75, word overlap ≤ 50), section completeness 0.15, date consistency 0.10. A component that cannot be scored has its weight shared among the others [F]. **Truthfulness**: `writing_quality.fact_violations(before, after, known_terms, allowed_additions)` flags any number added or dropped and any "fact token" (tool, name, skill) added or dropped, except allowed additions. `resume_preservation.py` locks company, title, years and institution per entry and raises `GROUNDING_REVIEW_REQUIRED` below 0.45 similarity. `keyword_forcing.py` lets a missing keyword in only after the user attests "I have this", and places it in the skills list or summary plus at most 2 existing lines, each of which "must keep all its facts and add nothing but the keyword" [F, code read through the GitHub API] | **Apache-2.0** [F] | **Adapt.** Port the *ideas* and small functions (`fact_violations`, the protected-fields list, the attestation gate, the score weights) into our own modules, with attribution in a NOTICE if code is copied. Do not adopt the app: it is a second stack (Next.js, LiteLLM, Python 3.13). |
| **Jobscan** (commercial) | Match rate 0–100%. Priorities in order: hard skills, education (only when an advanced degree is asked for), job title, soft skills, other keywords. Word count and measurable results do not count. Recommended target: 75%, though 65% is "often fine" [F, [Jobscan tutorial](https://Jobscan.co/jobscan-tutorial)]. The formula is not published. | Proprietary | **Learn from.** Weight hard skills above all, then title. Show a percentage, but label it "coverage of this JD", not "ATS score". |
| **Teal** (commercial) | The Match Score counts how many JD keywords appear in the resume. Teal says it guides alignment and does **not** predict an ATS result [F, [Teal help](https://intercom.help/tealhq-9a9274919b13/en/articles/9524864-using-job-matching)] | Proprietary | **Learn from** the honest labelling. |
| **Rezi** (commercial) | A 0–100 score per posting, with missing hard and soft skills. A reviewer says it "mostly counts keywords" [secondary: [Scoutify review](https://scoutify.com/blog/rezi-review/)] | Proprietary | **Learn from** (minor). |
| **ResumeWorded** | Not researched within the search budget | Proprietary | Unverified |
| **KeyBERT** | Embedding-based keyphrase extraction (sentence-transformers) | **MIT** [F, GitHub API] | **Reject for MVP.** It pulls in torch and an embedding model for little gain. Skill terms are a closed vocabulary that a dictionary plus the LLM covers better [O]. |
| **YAKE** (LIAAD) | Statistical keyphrase extraction with no training | **AGPL-3.0** per its LICENSE file ([repo](https://github.com/LIAAD/yake)); GitHub reports NOASSERTION and conda-forge says GPL-3.0 [F] | **Reject.** It is copyleft in a public repo, and its keyphrases ("strong communication") are not skills. |
| **SkillNer** | A spaCy matcher over the EMSI/Lightcast skills database | **MIT** code; last push 2024-01-28 [F]. The licence of the bundled skills DB is unverified | **Learn from / reject.** Our `keywords.py` already does n-gram skill matching with aliases. |
| **spaCy PhraseMatcher** | Token phrase matching | MIT (not checked this session) | **Reject** as a dependency: `keywords.overlap` already does this job. |
| **O\*NET** Technology/Software Skills | US occupational skills database, including "hot technologies" | **CC BY 4.0** [F, [O\*NET database](https://www.onetcenter.org/database.html)] | **Adapt** as a JD skill dictionary: a generated alias YAML with attribution. US-centric, but tool names are universal. |
| **ESCO** | EU skills taxonomy, with CSV and ODS downloads and an API | API under EUPL 1.2 [F, [ESCO](https://esco.ec.europa.eu/en/use-esco)]; data reuse terms **unverified** | **Learn from.** Use it only if O\*NET falls short; its skills are wordier ("use Python") and harder to match. |

**Takeaway [I]:** no product publishes a validated "ATS score". Every
inspectable score (Resume-Matcher, Teal) is keyword coverage plus a few
structure checks. The app's own `keywords.overlap` (consecutive tokens, alias
folding, a multi-word weight of 2, ambiguity guards for "go", "c" and "r") is
already the right core.

---

## 4. A truthful tailoring method

### 4.1 What is allowed and what is not [O, from the owner's brief]

| Allowed | Not allowed |
|---|---|
| Spell a skill the person has the way the JD spells it ("ML" → "machine learning"; "Postgres" → "PostgreSQL"; "k8s" → "Kubernetes"), only through an **alias table of true synonyms** | Adding any skill, tool, employer, title, degree, date, number or certification that is not in the source |
| Reorder bullets within one job, and reorder the skills list, by relevance to the JD | Moving a bullet to another job, merging bullets across jobs, inventing a bullet |
| Rewording a bullet to surface a JD term **already in that bullet** (or a true synonym of one) | Moving a skill from the skills list into a bullet where it was not ("Built X with Docker" when Docker appears only in the skills list): that changes the claim |
| Rewriting the summary using only skills and facts present somewhere in the resume | Generalisations that upgrade a claim ("Spring" → "Spring Boot", "used" → "led", "message queue" → "Kafka") |
| A headline equal to the target title (an aim, not a claim), if the owner allows it | Changing any past job title; hidden or white text; keyword blocks |
| Dropping or condensing low-relevance bullets (page budget) | Dropping numbers *within* a kept bullet |

Missing JD keywords go into a **report** shown to the user, not into the resume.
Resume-Matcher shows a sensible escape hatch [F]: the user may attest "I have
this", and only then may the term enter, in the skills list and at most a few
lines. [O] Store attestations in `config/profile.overrides.yaml` (a list the
user owns) so they hold for every future JD.

### 4.2 Detecting fabrication: layered, with deterministic checks first [O]

1. **Prevention by structure.** The model never sees fields it may not change.
   Employer, title, location, dates, institution and degree are copied from the
   parsed master resume into the output by code. The model receives
   `{bullet_id, text}` items and returns `{bullet_id, text, keywords_used}`. Code
   rejects unknown ids, missing ids and duplicates. Every output bullet traces to
   exactly one source bullet by id.
2. **Per-bullet diff** (deterministic, modelled on Resume-Matcher's
   `fact_violations` [F]):
   - *Numbers:* the multiset of numbers with their units (`35%`, `S$1.2M`,
     `3x`, `2024`) must be identical before and after.
   - *Fact tokens:* any token that is in the skill dictionary, capitalised
     mid-sentence, or an acronym, and that appears in the output, must appear in
     the source bullet **or** be the alias of a source-bullet token **or** be an
     attested term. No fact token from the source may be dropped.
   - *Keyword claims:* every `keywords_used` entry must actually appear in the
     output text, and must map (via the alias table) to a term in the source
     bullet.
   - *Length:* the output stays within ±40% of the source length, to stop
     padding.
   A failed bullet **falls back to the original text**. It is never "fixed" by a
   second free-form attempt that goes unchecked. One retry with the violation
   listed is fine, and the retry passes through the same check.
3. **Resume-wide invariants** (golden-test oracle): the sets of employers,
   titles, dates, degrees, institutions and numbers are equal between the source
   and the output, and the skills list ⊆ source skills ∪ attested.
4. **LLM judge (advisory only).** A second pass asks: "does B claim anything A
   does not?", answered in a JSON schema. [O] A 14B model checking its own kind
   of output is a weak oracle. Use it only to flag items for the user's review,
   never to approve.
5. **Human diff review.** A side-by-side diff with the changed spans
   highlighted, plus the missing-keyword report. [O] Required in the MVP before a
   file can be marked "sent" or used by auto-apply.

---

## 5. Pipeline design

```
master resume (parsed once per resume hash, owner-confirmed)
        │
JD text (store.jobs.jd_text) ──► [A] keyword extraction ──► JD keyword set {term, required|preferred, variants}
        │                                         │
        └────────────► [B] map resume ↔ keywords ◄┘   present_exact | present_variant | missing
                               │
                    [C] score before (deterministic)
                               │
     [D] rewrite: deterministic variant swaps → LLM bullet rewrite (JSON schema) → §4.2 validator
                               │
                    [E] score after · missing-keyword report
                               │
     [F] render DOCX from the ATS template → round-trip parse check → (optional) PDF
```

**0. The master resume** (a new prerequisite). Profile ingest today keeps only
summary, skills and titles [F, `_DERIVED_KEYS`]. Tailoring needs the full
structure: contact, sections, entries and bullets with ids. [O] Parse it once per
resume hash with the LLM into JSON, then **check every leaf string against the
extracted text** (after normalising whitespace and bullet glyphs). A string that
is not found is a parse error, never accepted. Cache the result, for example in
`data/master_resume.json`, and show it once for the owner to confirm. A DOCX
source can be parsed structurally by code (paragraph styles, list numbering);
a PDF source needs the LLM.

**A. JD keyword extraction (deterministic plus LLM, with the LLM checked).**
- Deterministic: run `keywords.overlap(jd_text, dictionary)`, where the
  dictionary = profile skills ∪ O\*NET technology terms ∪ a hand-kept alias YAML.
- LLM (one call, `format` = JSON schema): `{title, required:[str],
  preferred:[str], acronym_pairs:[[short,long]]}`. **Keep only terms that occur
  in the JD text**, matched with the same tokeniser, so a term the model
  invented never enters the set. Required vs preferred comes from section cues
  such as "Requirements" or "Nice to have", which the LLM handles well.
- Union the two. Required terms weigh 2 and preferred terms 1, multiplied by
  the existing multi-word weight.

**B. Mapping.** For each JD term: `present_exact` (the term itself is in the
resume) / `present_variant` (an alias is in the resume, recording where) /
`missing`. [O] Do not let the LLM decide "the resume implies this skill" in the
MVP. That is the fabrication door. Put such terms in the report as
"possibly relevant, confirm?".

**C/E. Score.** `coverage = Σ weight(present terms) / Σ weight(all JD terms)`,
computed before and after. Count a term as present after tailoring only if it
appears in the JD's own spelling. Add a title-match flag in Resume-Matcher's
style. [O] Label it "JD keyword coverage", never "ATS score". By construction,
the after score can only rise through variant spellings, headline/summary
placement and attested terms. That ceiling is honest and should be shown.

**D. Rewrite.**
- *Deterministic pass first:* replace each `present_variant` spelling with the
  JD's spelling in place (with the long form in parentheses on first use when
  the JD uses the acronym, e.g. "Kubernetes (K8s)"). No model is needed, and
  this alone delivers most of the keyword gain [I].
- *LLM pass:* one call per job entry (3–6 bullets), not one call per bullet and
  not one call for the whole resume. That keeps context small and failures
  local [O]. Prompt pattern:
  - system: the role, then the allowed and forbidden lists from §4.1, stated as
    rules plus a pair of examples showing a violation and its correct version;
  - user: the JD's required terms *that this entry already supports* (computed
    by code, so the model is told exactly which words it may surface), the
    entry's bullets as `[{id, text}]`, and the instruction "return every id
    exactly once, in relevance order";
  - schema: `{"bullets":[{"id":int,"text":str,"keywords_used":[str]}]}`.
  - The summary is a separate call, given the resume's skill list and the top JD
    terms present.
- *Temperature:* the app runs everything at 0 today [F, `backends.py`]. Qwen's
  card recommends 0.7 / top-p 0.8 / top-k 20 for non-thinking mode, and warns
  against greedy decoding (the warning is stated for thinking mode) [F,
  [Qwen3-14B card](https://huggingface.co/Qwen/Qwen3-14B)]. [O] Use 0.2–0.3 with
  top-k 20 for the rewrite. That gives some variety while staying close to
  deterministic, and the validator catches drift. Keep 0 for extraction. Record
  the model and options with each tailored file.

**F. Output.** Two ways to build the file:

| Option | Pros | Cons |
|---|---|---|
| Edit the original DOCX's runs in place (python-docx) | Keeps the owner's design | Works only when the source is a DOCX, and the app prefers `resume.pdf` [F, `RESUME_NAMES`]. Word splits text across runs, so a rewrite has to collapse a paragraph's runs and loses inline formatting. Any column, table or text-box layout in the original stays unsafe to parse. |
| **Render from one clean ATS template** (python-docx builds a single-column DOCX) | Works for PDF and DOCX sources. Parse-safe by construction, deterministic, testable, and uses no new dependency | Does not look like the owner's original |

[O] **Recommend: render from a template.** Keep in-place editing as a later
option for DOCX sources only.

PDF on Windows, if wanted:

| Route | Facts | Assessment [O] |
|---|---|---|
| `docx2pdf` | Needs Microsoft Word installed and drives it through pywin32/COM. MIT licence; last release 0.1.8 on 2021-12-11 [F, [PyPI](https://pypi.org/project/docx2pdf/)] | Best fidelity *if Word is present*. Unmaintained, but it is a thin wrapper, so call Word COM directly instead. |
| LibreOffice headless (`soffice --headless --convert-to pdf`) | A large separate install (not verified this session) | A good fallback. Fidelity is fine for a simple single-column template. |
| HTML → PDF: Edge headless `--print-to-pdf`, or Playwright/Chromium (Resume-Matcher's choice [F]) | Edge ships with Windows 11 [I]. Playwright needs a browser download. WeasyPrint needs GTK/Pango on Windows (not verified this session) | Needs a second template (HTML) that must match the DOCX one. Avoid WeasyPrint. |

[O] **Recommendation: produce DOCX only in the MVP.** Every ATS reviewed
accepts it, and it avoids any converter. Add PDF with **Word COM first,
LibreOffice as the fallback, and a "PDF unavailable, use the DOCX" message**
when neither is installed. Run the round-trip check on whichever file is
produced.

---

## 6. Qwen3-14B fitness

- [F] 14.8B parameters, Apache-2.0. Native context is 32,768 tokens
  (131,072 with YaRN, which "may impact performance on shorter texts").
  Thinking is on by default. `enable_thinking=False` turns it off entirely, and
  the `/no_think` soft switch works only while thinking is enabled
  ([Qwen3-14B card](https://huggingface.co/Qwen/Qwen3-14B)). The app already
  sends `"think": false` to Ollama [F, `backends.py`], so `/no_think` is not
  needed.
- [F] Ollama's `format` accepts a full **JSON schema**, and generation is
  constrained to it. The docs suggest Pydantic for the schema, saying "return as
  JSON" in the prompt, and temperature 0
  ([Ollama blog, 2024-12-06](https://ollama.com/blog/structured-outputs)). The
  app passes `"format": "json"` today [F]. The tailor should pass the schema
  object, which needs a small, backwards-compatible `format=` argument on
  `OllamaBackend.complete`.
- [F] The app's `num_ctx` is 16,384 [`backends.py`]. [I] A JD (about 1–3k
  tokens), one job entry, the rules and the term list come to about 3–5k
  tokens, which fits easily.
- **Latency, an estimate [I]:** measured Ollama speed for qwen3:14b on an RTX
  4080 is about 62 tok/s
  ([glukhov.org](https://www.glukhov.org/post/2026/01/choosing-best-llm-for-ollama-on-16gb-vram-gpu/)).
  One estimate for an RTX 5080 (the owner's GPU, per PRD line 114) is about
  80 tok/s
  ([willitrunai, an estimate](https://willitrunai.com/ja/can-run/qwen-3-14b-on-rtx-5080-16gb)).
  About 15 bullets at about 60 output tokens each, plus JSON overhead, is
  roughly 1.2–1.5k output tokens, or **about 15–25 s of generation**. Add
  keyword extraction (about 3–5 s), the summary (about 2–3 s), prompt
  processing for 4–5 calls (a few seconds) and retries for failed bullets
  (+20–30%). **Expect about 30–60 s per tailored resume.** That suits a
  background job using the existing job runner, not a synchronous request.
- **Strengths and weaknesses [O, not sourced]:** a 14B model in non-thinking
  mode is good at following a schema and at rephrasing locally. It tends to
  embellish (adding "spearheaded", vague claims of impact), to obey negative
  rules imperfectly, and to "helpfully" add a JD tool. That is why §4.2 has to
  be code, not prompt. A constrained schema prevents malformed JSON, not false
  content. If quality falls short, try thinking mode for the summary only (a
  slower, longer call), not for the bullets.

---

## 7. Temporary storage

- [F] `.gitignore` ignores `data/*.pdf` and `data/*.docx`, which match the
  **top level of `data/` only**. **A file in `data/tailored/` would *not* be
  ignored, and the repo is public.** [O] Add `data/tailored/` (and
  `data/master_resume.json`) to `.gitignore` in the same change that creates
  them. Add a test that asserts it, like the existing personal-data entries.
- [O] Layout: `data/tailored/<job_id>/<Firstname_Lastname_Resume>.docx`, plus a
  `tailored` table in `store.py`, the only code that touches the database
  [F, OVERVIEW]. Columns: `job_id, resume_hash, jd_hash, model, options_json,
  created_at, status (draft|sent), path, file_sha256, score_before, score_after,
  missing_json, diff_json`.
- [O] **Retention:**
  - A draft is deleted after 7 days. This mirrors the M17 JD time-to-live
    (`purge_descriptions`), and the purge can run in the same place.
  - A draft is invalidated when the resume hash or the JD hash changes.
  - The **sent** file (marked when the user clicks "Mark applied", or when
    auto-apply uploads it) is kept, with its SHA-256, **until the application
    reaches a closed status** (rejected, withdrawn or offer settled) **plus 30
    days**. That way the owner can see exactly what the recruiter saw at
    interview time.
  - Purging deletes the file but keeps the row (scores, missing terms), so the
    history survives without the document.
- [O] **Privacy:** everything stays local, with no cloud LLM. Never log resume
  text to the Developer tab's job log; log only counts and ids. A tailored file
  holds the same personal data as the resume, so treat it the same way.

---

## 8. Golden-case plan (synthetic, hand-checkable)

All three cases are invented and contain no real person's data. Each gives a
resume excerpt, a JD excerpt, the expected keyword sets and the
**must-not-change** invariants. The oracles are deterministic: compare sets of
strings and numbers, not the wording.

### Case A: new-grad backend (variant mirroring)
- **Resume (Jane Tan):**
  - Header: "B.Eng. Computer Engineering, Nanyang Example University, 2025".
  - Job: "Software Engineering Intern, Acme Logistics Pte Ltd, May 2024 – Aug 2024":
    - "Built REST APIs in Python and Postgres for shipment tracking."
    - "Deployed services on k8s with GitHub Actions; cut p95 latency 35%."
    - "Trained an ML model to predict delivery delays (82% accuracy)."
  - Skills: Python, Postgres, k8s, GitHub Actions, ML, Git.
- **JD:** "Backend Engineer (Graduate)". Required: Python, PostgreSQL,
  Kubernetes, REST APIs, CI/CD, Go. Preferred: machine learning, Kafka.
- **Expected keywords:**
  - `present_exact` = {Python, REST APIs}
  - `present_variant` = {PostgreSQL←Postgres, Kubernetes←k8s,
    machine learning←ML}
  - `missing` = {Go, Kafka, CI/CD}

  CI/CD is in the missing list only if "GitHub Actions" is not in the alias
  table as an instance of CI/CD. [O] Treat a tool as an instance of a practice
  only through an explicit alias, and decide that in the alias YAML so the test
  pins it.
- **After tailoring:** "PostgreSQL", "Kubernetes" and "machine learning" appear;
  "Go" and "Kafka" do **not** appear anywhere; the skills list ⊆ {Python,
  PostgreSQL, Kubernetes, GitHub Actions, machine learning, Git}.
- **Invariants:** Acme Logistics Pte Ltd; Software Engineering Intern; May 2024 –
  Aug 2024; B.Eng. Computer Engineering; Nanyang Example University; 2025; the
  numbers {35%, 82%, 95 (in p95)}.
- **Trap:** the ambiguous "Go" must not be "found" in "go-live" if a bullet
  contains it (this exercises `keywords._AMBIGUOUS`).

### Case B: data analyst (no tool swapping)
- **Resume (Wei Ling Lim):**
  - Job: "Business Analyst Intern, Example Bank, Jan 2025 – Jun 2025":
    - "Automated 40 weekly reports with SQL and Python (pandas)."
    - "Built Tableau dashboards tracking S$1.2M in card spend."
    - "Analysed pivot tables in Microsoft Excel for the ops team."
  - Skills: SQL, Python, pandas, Tableau, Excel.
- **JD:** "Data Analyst". Required: SQL, Power BI, Excel, stakeholder
  management. Preferred: A/B testing, Python.
- **Expected:**
  - `present_exact` = {SQL, Python}
  - `present_variant` = {Excel←Microsoft Excel}
  - `missing` = {Power BI, A/B testing, stakeholder management}
- **Must hold:** "Tableau" stays in the dashboards bullet, and "Power BI"
  appears **nowhere** (the classic fabrication: the same category of tool,
  swapped). "stakeholder management" is not added; "for the ops team" stays.
- **Invariants:** Example Bank; Business Analyst Intern; Jan 2025 – Jun 2025;
  the numbers {40, S$1.2M}.

### Case C: fintech Java (no upgrading a claim)
- **Resume (Arjun Nair):**
  - Job: "Software Engineer, Example Pay Pte Ltd, Jul 2023 – present":
    - "Developed payment microservices in Java and Spring, exposing REST
      endpoints."
    - "Integrated RabbitMQ message queues; processed 2M transactions/day."
    - "Wrote KYC document checks reducing manual review by 30%."
  - Education: "BSc Computer Science, 2023".
- **JD:** "Backend Engineer, Payments". Required: Java, Spring Boot, REST APIs,
  Kafka, microservices. Preferred: AML/KYC, Docker. Also: "Must be a Singapore
  Citizen/PR" (a knockout question, not resume content).
- **Expected:**
  - `present_exact` = {Java, microservices, KYC}
  - `present_variant` = {REST APIs←REST endpoints}
  - `missing` = {Kafka, Docker, AML}
  - `needs_confirmation` = {Spring Boot (resume says "Spring")}
- **Must hold:** "Spring Boot" does **not** appear unless attested; "Kafka" does
  not replace "RabbitMQ"; "present" is not changed to an end date. The
  citizenship requirement appears in the report as an *application question for
  the user*, never in the resume.
- **Invariants:** Example Pay Pte Ltd; Software Engineer; Jul 2023 – present;
  BSc Computer Science; 2023; the numbers {2M, 30%}.

**The oracle tests to write [O]:**
1. Keyword-set equality for extraction and mapping, with the LLM mocked to
   return a fixed JSON *plus one invented term* (which must be dropped by the
   "occurs in the JD" check).
2. Invariants: the sets of employers, titles, dates, degrees and numbers are
   equal between the source and the output.
3. The forbidden terms are absent.
4. The §4.2 validator rejects four hand-written bad rewrites per case: an added
   number, a dropped number, a swapped tool and a moved skill.
5. The rendered DOCX passes the round-trip parse check.
6. Coverage after tailoring ≥ coverage before, with the exact values computed by
   hand.

---

## Recommended design (walking skeleton → MVP) [O]

Fit the existing layering: a new stage package `src/jobscraper/tailor/`
(`keywords_jd.py`, `master.py`, `rewrite.py`, `validate.py`, `render.py`). An
orchestrator function or CLI command wires it together. Only `backends.py`
talks to Ollama and only `store.py` talks to SQLite, and
`tests/test_layering.py` must keep passing.

1. **Skeleton (no LLM, no file):** `python -m jobscraper tailor <job_id> --report`.
   It loads the resume text and `jd_text`, runs the deterministic extraction and
   mapping (profile skills + alias YAML), and prints present, variant and
   missing terms with a coverage score. Golden cases A–C for mapping pass.
2. **Master resume:** an LLM parse to JSON with the "every leaf occurs in the
   source" check, cached by resume hash, plus a CLI or UI confirm step.
3. **Render:** DOCX from the template with **deterministic variant swaps
   only**, then the round-trip check. Even at this step there is a usable,
   truthful tailored file.
4. **LLM layer:** JD term extraction (schema + occurs-in-JD filter), bullet
   reorder and rewrite per entry (schema) with the §4.2 validator and fallback,
   and the summary rewrite. Add a `format=<schema>` parameter to
   `OllamaBackend.complete`.
5. **UI and storage (MVP done):**
   - A "Tailor resume" button on the Inbox and Applications detail views starts
     a background job.
   - A result panel shows the before/after coverage, the missing terms with
     "I have this" (written to overrides), the knockout-style requirements
     detected, and a side-by-side diff.
   - Download DOCX.
   - A `tailored` table, `data/tailored/`, the `.gitignore` entry and the purge.
   - "Mark applied" marks the latest reviewed draft as `sent`.
6. **Later:** PDF via Word COM or LibreOffice; an advisory LLM judge; in-place
   editing of a DOCX source; the auto-apply hand-off (it uploads only a `sent`-
   eligible, reviewed file whose SHA-256 is recorded).

## Decisions the owner must make

| # | Decision | Options | Recommendation [O] |
|---|---|---|---|
| D1 | Which repo hosts this | (a) personal JobScraper (its auto-memory notes the `personal` branch is *frozen*); (b) JobScraper-Cloud; (c) both, personal first | Decide explicitly before any build. The brief fits either, but the PRD row "Résumé tailoring: Not requested" must change wherever it lands. |
| D2 | Output format | DOCX only / DOCX + PDF / same as the source | **DOCX only for the MVP.** Add PDF later via Word COM with a LibreOffice fallback. (Is Word installed on the machine?) |
| D3 | Layout | A clean ATS template / keep the original DOCX look | **Template.** It parse-safes the output and works from a PDF source. |
| D4 | Review gate | Always review the diff before use / validator only, auto-use | **Always review in the MVP.** Auto-apply may use only reviewed files at first. |
| D5 | Missing skills the owner does have | Never add / "I have this" attestation saved to overrides / per-JD only | **Attestation saved to overrides**, so it is truthful and reusable. |
| D6 | Headline with the target title | Allow (opt-in) / never | **Allow, opt-in.** It is a stated aim, not a claim. Past titles are never touched. |
| D7 | Practice ↔ tool aliases (e.g. GitHub Actions ⇒ CI/CD) | Strict synonyms only / curated "instance-of" aliases | **A curated alias YAML that the owner can edit.** Each entry is a deliberate truth claim. |
| D8 | Retention | Drafts 7 d; sent until closed + 30 d / keep sent forever / delete right away | **Drafts 7 d; sent until closed + 30 d**, keeping the row and metadata. |
| D9 | Length budget | Keep the source's page count / allow growth | **Keep the source's page count.** Drop the least relevant bullets rather than overflow. |
| D10 | Sampling for the rewrite | 0 (as today) / 0.2–0.3 / Qwen's 0.7 | **0.2–0.3**, with the validator as the guard; settle it on the golden cases. |

## Unverified items

- The details of Greenhouse's auto-reject rules on application questions (from a
  search snippet only), and its "Talent Matching" feature (third-party only).
- Workday HiredScore's August 2026 move to an LLM (from a search summary; the
  release note was not opened). Whether Workday has knockout or auto-disqualify
  questions (not researched).
- Lever's knockout auto-archive (from a search summary of the Help Center; the
  setup article was not found).
- iCIMS Role Fit mechanics and the AEDT audits (secondary sources only).
  SuccessFactors: which SAP KB states "Auto Disqualified"; the KBs are old.
- The Preptel origin of the "75%" figure (secondary). The Enhancv survey has
  n = 25, comes from a vendor, and was read through press coverage.
- ESCO's data reuse licence. The licence of SkillNer's skills DB. spaCy's
  licence (MIT, not checked this session).
- ResumeWorded's scoring (not researched).
- LibreOffice install size and conversion fidelity; WeasyPrint's GTK needs on
  Windows; that Edge's headless `--print-to-pdf` works on the owner's machine.
- Qwen3-14B speed on the RTX 5080 (the 80 tok/s figure is an estimate; measure
  with `ollama run qwen3:14b --verbose`). The 30–60 s figure per tailoring is
  this researcher's estimate.
- Qwen3-14B's tendency to embellish under constrained rewriting (opinion, no
  benchmark cited).
- The parse-safety rules about tables, columns, headers, fonts and file naming
  (common advice; no primary ATS or parser source found).
- Whether `jobs.jd_text` is always plain text or sometimes HTML (`html_to_text`
  exists in `scrape/adapters.py`; check before using it as extraction input).
