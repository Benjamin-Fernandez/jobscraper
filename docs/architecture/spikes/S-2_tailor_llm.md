# Spike S-2: can local Qwen3-14B do the tailor's per-entry rewrite? (Q-06)

Author: software-engineer, 2026-11-02. Branch `spike/Q-06-tailor-llm`. Feeds `tailor_design.md` §7, §8, §14 (`tailor.llm`) and NF-07 (≤ 90 s per job). Scratch code was throwaway (not committed); this file is the only artefact.

## Verdict (short)

- **Speed and JSON validity: pass with a very large margin.** About 1.5 s per entry, about 6 s per four-entry resume (budget 90 s). 177 of 177 structured calls returned valid JSON with the right ids.
- **Truthfulness: the validator catches what the model actually did wrong, but the model barely rewrites anything.** 78 to 79 % of bullets come back unchanged; on real JDs, 0 to 2 % of bullets end up different from the post-swap text. Coverage after the LLM step equalled coverage after the deterministic swaps in **all 54 runs**.
- **Recommendation: keep `tailor.llm: false` as the default.** The rewrite costs little but adds nothing measurable to the F-21 coverage metric, because §7.2's ALLOWED TERMS are, by construction, terms the swaps have already surfaced. If M21 ships it anyway, apply the fixes under "Recommendations".

## Setup

| Item | Value |
|---|---|
| Model | `qwen3:14b` (14.8 B, Q4_K_M), `config.yaml` `budget.ollama_model` |
| GPU | NVIDIA RTX 5080, 16 GB (idle before the run; about 10 GB used while loaded) |
| Ollama | 0.40.13, `/api/chat`, `stream:false`, `think:false` (accepted), `format` = the §7.2 JSON schema (grammar-enforced) |
| Options | `temperature` 0 / 0.25 / 0.5, `top_k` 20, `num_predict` = 120 n + 200, `num_ctx` 16384 (as config) |
| Seeds | temperature 0: seed 7 for all 3 repetitions (so they are the same run). Temperature > 0: seeds 7, 8, 9 for the three repetitions (a fixed seed would make repetitions identical) |
| Prompt / schema / validator | Exactly §7.2 (system prompt verbatim, user prompt format, schema with `minItems`/`maxItems`/`enum`/`maxLength`) and §8.1 (ids, numbers multiset, fact tokens, keywords, length 0.6 to 1.4). One retry with `THESE REWRITES BROKE THE RULES` for failing bullets, then fallback to the post-swap bullet. Deterministic swaps (§6.2, article fix) feed the LLM, as in the design |
| Cases | Golden A, B, C (synthetic, from §15, deterministic oracle reproduced: A 29 % to 64 %, B 50 % to 50 %, C 38 % to 54 %, and all three expected post-swap bullet sets matched). R1, R2, R3 = three accepted postings from a copy of the DB ("Software Engineer", "Software Engineer, Ministry of Law", "Data Engineer (Data & Systems Engineering)"), each tailored with the **same synthetic new-grad resume** written in scratch (4 rewritable experience/project entries, 11 bullets). The DB copy was deleted afterwards |
| Runs | 6 cases x 3 temperatures x 3 repetitions = 54 resume runs (45 entries, 126 bullets per temperature). Plus 9 stress runs (see below). Total model time about 10 minutes |
| Dictionary | Golden `aliases_golden.yaml` terms plus about 35 generic extra terms so real JDs have hits. No LLM JD extraction (§4.4) in this spike; terms are dictionary-only |

## Results

### By temperature (all cases pooled; 126 bullets, 45 entries per row)

| T | JSON valid | Bullets unchanged on 1st output | 1st-pass rejected (any rule) | of which hard (numbers/facts/length) | of which keyword-only | Retry rescued | Final fallback | Bullets finally different from post-swap | s per entry (mean / max) | s per resume (mean / max) |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 57/57 | 79 % | 12 % (15) | 4.8 % (6) | 7.1 % (9) | 0 | 12 % | 9 % | 1.5 / 4.3 | 3.8 / 8.2 |
| 0.25 | 60/60 | 79 % | 16 % (20) | 4.8 % (6) | 11.1 % (14) | 0 | 16 % | 10 % | 1.5 / 3.5 | 3.8 / 7.8 |
| 0.5 | 60/60 | 78 % | 16 % (20) | 4.8 % (6) | 11.1 % (14) | 0 | 16 % | 10 % | 1.5 / 3.5 | 3.7 / 7.8 |

Real-JD resumes (R1 to R3, 4 entries each) take 5.3 to 7.8 s per resume at every temperature. Mean output is 119 tokens per entry; 1.31 calls per entry including retries. Temperature made no practical difference to validity, speed or number of changes.

### Per case (mean of 3 repetitions; coverage = design formula)

| Case | Bullets (3 reps) | Changed vs post-swap, T 0 / 0.25 / 0.5 | Hard rejections | Keyword-only rejections | Coverage before to after swaps to after LLM | s per resume |
|---|---|---|---|---|---|---|
| A | 9 per T | 6 / 6 / 6 (67 %) | 0 | 0 | 29 % to 64 % to 64 % | 1.5 |
| B | 9 per T | 2 / 2 / 2 (22 %) | 0 | 0 | 50 % to 50 % to 50 % | 1.3 |
| C | 9 per T | 3 / 3 / 3 (33 %) | 3 of 9 every T (bullet 1, FACT_DROPPED `spring`) | 0 | 38 % to 54 % to 54 % | 2.0 to 2.1 |
| R1 | 33 per T | 0 / 0 / 0 | 0 | 3 / 5 / 5 | 57 % to 57 % to 57 % | 5.3 to 6.1 |
| R2 | 33 per T | 0 / 0 / 0 | 3 per T (R2 bullet 'Trained a scikit-learn model...', LENGTH) | 3 / 6 / 6 | 56 % to 67 % to 67 % | 6.1 to 6.7 |
| R3 | 33 per T | 0 / 1 / 2 | 0 | 3 / 3 / 3 | 25 % to 25 % to 25 % | 5.3 to 6.4 |

(Counts are summed over the 3 repetitions at each temperature. Coverage is identical in all repetitions.)

### Why the validator rejected bullets (first pass, all temperatures, unique examples)

| Code | Count (T 0 / 0.25 / 0.5) | Example (source -> model output) |
|---|---|---|
| FACT_DROPPED | 3 / 3 / 3 | "Developed payment microservices in Java and Spring, exposing REST APIs." -> "Developed Java-based payment microservices with REST APIs." (dropped `spring`: correct rejection) |
| LENGTH | 3 / 3 / 3 | "Trained a scikit-learn model on 50k tweets reaching 88% F1." -> "...achieving 88% F1 score for sentiment analysis." (89 vs 59 chars; also an invented "sentiment analysis") |
| KEYWORD_UNSUPPORTED | 18 / 24 / 24 | The text was fine; `keywords_used` held a phrase that is not a dictionary term, e.g. "F1 score", "Jupyter notebook", "unit tests", "ML approaches", "REST", or an ALLOWED TERM that was not in the bullet ("ML (not in text)"). These are validator false positives. **No keyword-only rejection ever hid a real fabrication** |
| FACT_ADDED (on retry only) | 6 / 6 / 6 | Retry outputs introduced a new fact (e.g. `machine learning` into a scikit-learn bullet) |

No NUMBER_ADDED or NUMBER_DROPPED occurred in any model output across 54 runs; the model never altered a digit.

Retry value: 59 retries attempted, **0 rescued a bullet**. Where the first output broke a hard rule the retry either repeated the same thing or broke a different rule.

### Stress test (outside the design: ALLOWED TERMS loosened to every JD term, T 0.25, 3 reps x R1 to R3 = 9 runs)

The model was told it could surface terms the bullet does not support (e.g. CI/CD, ML, Terraform). Result: 1 hard rejection of 99 bullets (it added "ML" to a scikit-learn bullet; caught as FACT_ADDED), 0 bullets changed, 0 fabricated terms passed. 5.0 s per resume. So prompt injection of unsupported terms is resisted well, and the validator would have caught the one slip.

## Examples (accepted rewrites; every changed bullet that passed, 8 unique across all runs)

| Case | Before (post-swap) | After |
|---|---|---|
| A | Built REST APIs in Python and PostgreSQL for shipment tracking. | Built REST APIs using Python and PostgreSQL for shipment tracking. |
| A | Deployed services on Kubernetes with GitHub Actions; cut p95 latency 35%. | Deployed services on Kubernetes using GitHub Actions; reduced p95 latency by 35%. |
| B | Automated 40 weekly reports with SQL and Python (pandas). | Automated 40 weekly reports using SQL and Python (pandas). |
| C | Wrote KYC document checks reducing manual review by 30%. | Implemented KYC document checks, reducing manual review by 30%. |
| R3 | Compared ML approaches and documented results in a Jupyter notebook. | Compared ML approaches and documented findings in a Jupyter notebook. |
| R3 | Built REST endpoints in Java with Spring for an inventory service used by 12 stores. | Built Java-based REST endpoints with Spring for an inventory service used by 12 stores. |

Rejected examples (kept original): C bullet 1 above; R2 "Trained a scikit-learn model..." above.

**Hand inspection of passed output:** no hallucinated tool, number, employer or outcome got through in the 8 unique accepted rewrites. The only questionable ones are mild: "Wrote" -> "Implemented" (a small claim upgrade) and "Java-based" (a new modifier). Every change is cosmetic ("using"/"with", "cut" -> "reduced ... by"). None adds a JD keyword the post-swap bullet lacked, which is why coverage does not move.

## Validator gaps (hand-made probes, no model; same §8.1 implementation)

| Probe (source -> bad rewrite) | Result |
|---|---|
| "Developed ..." -> "Led development of ..." ; "Wrote ..." -> "Architected ..." | **Missed** (verb/seniority upgrade, the very example in the prompt) |
| "Contributed to an inventory service..." -> "Owned an inventory service..." | **Missed** |
| "Cut p95 latency 35%" -> "Increased p95 latency 35%" | **Missed** (direction flip) |
| "team of three" -> "team of four"; "Mentored interns" -> "Mentored five interns" | **Missed** (number words are not digits) |
| "...reports." -> "...behind nginx..." (tool not in dictionary, lowercase) | **Missed** |
| "Built dashboards..." -> "Grafana dashboards built..." (unknown capitalised tool as first word) | **Missed** (sentence-start exemption) |
| "...weekly reports" -> "..., significantly improving decision making" | Caught only incidentally by LENGTH |
| Unknown capitalised tool mid-bullet ("Built Grafana dashboards") | Caught (FACT_ADDED) |
| Added employer/product name ("for Stripe") | Caught (FACT_ADDED) |
| Spring -> Spring Boot | Caught (FACT_ADDED + FACT_DROPPED) |
| "2M" -> "2 million", "3M" -> "3,000,000", "30%" -> "30 percent" | Rejected (NUMBER_ADDED/DROPPED): safe, but also blocks legitimate reformatting |

Design-spec gap found while implementing §4.3 step 4: a list item such as `- Kafka` satisfies "title case, no sentence punctuation, <= 8 words" and is treated as a heading, which resets the "Nice to have" section and makes Kafka/Python/Docker count as required. Golden A, B, C oracles (29 %, 50 %, 38 %) are only reproduced if lines starting with a bullet marker (`-`, `*`, `•`) are never headings. The engineer needs that rule written into §4.3.

## Recommendations

1. **`tailor.llm` default: false.** Reasons: no coverage gain (0 of 54 runs), 0 to 2 % of real-resume bullets change, and each change is cosmetic. The benefit does not justify the validator gaps below, which only matter once the model is trusted to rewrite. Revisit if §4.4 LLM term extraction surfaces terms the dictionary misses and ALLOWED TERMS is redefined (see 4).
2. **Temperature:** no measurable difference between 0, 0.25 and 0.5. If enabled, keep 0.25 (D-60) or use 0 for reproducibility; the fixed `seed=7` makes 0.25 repeatable anyway.
3. **Validator (if the LLM stays in scope):**
   - Validate `keywords_used` only against the ALLOWED TERMS list passed in (the check "each entry in ALLOWED TERMS and in the bullet"), and ignore other strings. The current rule rejected 7 to 11 % of bullets for harmless phrases. Better: drop `keywords_used` from the schema; the fact check already covers it and it saves tokens.
   - Add a verb-class check: the first word's lemma may change only within a small curated synonym set (built, developed, created; wrote, authored; cut, reduced, decreased), and block an upgrade list (led, owned, managed, architected, spearheaded, directed, drove). Compare the leading verb and any "led/owned/managed" token anywhere in the output.
   - Add a word-level check: any alphabetic token in the output that is neither in the source, nor in ALLOWED TERMS, nor in a short stop/function-word list (about 150 words incl. "using", "with", "by", "and") fails as `WORD_ADDED`. This closes unknown lowercase tools, number words, adjectives ("scalable") and outcome clauses without a bigger dictionary.
   - Number words (one to twenty, "dozen", "hundred", "half") count as numbers.
   - Remove the sentence-start exemption for capitalised words that are not the source's own first word.
   - Direction words (cut/reduced/decreased vs increased/improved/grew) must not flip polarity (add a small polarity table).
   - Keep the strict digit rule; it never misfired on model output (0 NUMBER_ issues), only on hand reformatting.
4. **Prompt / design tweaks:** (a) ALLOWED TERMS as defined (already present in the bullet) leaves the model nothing to surface, so the step reduces to polishing; if value is wanted, the useful task is reordering (31 % of entries were reordered, relevance not measured in this spike) and that does not need rewriting at all, only a deterministic sort (§6.3). (b) Drop the retry: 0 of 59 rescued, it adds 31 % more calls and sometimes a new fabricated fact. Fall back directly. (c) Add "Keep the first word's meaning; do not replace the verb with a stronger one" to the system prompt (the model changed "Wrote" to "Implemented" unprompted).
5. **NF-07:** with the LLM on, a typical resume costs 5 to 8 s of model time (1.5 s per entry), well inside 90 s even for 15 entries plus the summary rewrite and JD extraction call. Cold model load was not measured here (the model was warmed with one call first; add about 10 to 20 s for a cold 14B load).

## Not measured

Summary rewrite (§9), LLM JD term extraction (§4.4), cold-start load time, quality of the model's bullet *order*, and behaviour on long (6+ bullet) entries. One stress run with a loose ALLOWED TERMS list was added; nothing else was tuned.
