# Outbox: software-engineer

Only `software-engineer` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD software-engineer → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

### 2026-11-02 software-engineer → coordinator
TYPE: handoff
RE: Q-06 / S-2 / F-22, NF-07; docs/architecture/spikes/S-2_tailor_llm.md
BODY: Spike done on branch spike/Q-06-tailor-llm. Qwen3-14B (qwen3:14b, Ollama 0.40.13, RTX 5080): 1.5 s per entry, about 6 s per resume, 177/177 calls valid JSON. 78-79% of bullets returned unchanged; real-JD resumes 0-2% changed; coverage after LLM == after swaps in 54/54 runs. Hard validator rejections 4.8% (all correct); keywords_used check gave 7-11% false positives; retry rescued 0/59. Validator misses verb upgrades, direction flips, number words, unknown lowercase tools. Recommend tailor.llm stays false; fixes listed in the report. Design gap: a "- Kafka" list line is read as a heading (§4.3 step 4); golden oracles need "bullet-marker lines are never headings".
STATUS: open
