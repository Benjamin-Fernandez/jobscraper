# ADR-0001: Drive Edge with Playwright on a dedicated profile

**Status:** Accepted (implements D-53)
**Date:** 2026-11-01
**Deciders:** Coordinator (D-53); architect (this record)
**Relates to:** PRD F-34, R-1, R-3; `apply_design.md` §8; spike `spikes/S-1_S-3_browser.md`

## Context

Auto-apply must fill and submit forms on employer sites from the owner's Windows 11 PC, in Microsoft Edge (the owner's default browser), from Python (the app's only runtime). The owner would like saved passwords to end up in their normal Edge.

Forces:
- Chromium 136+ ignores `--remote-debugging-port` on the default user-data directory; Playwright documents that automating the default profile is unsupported (brief §3.1).
- The app's layering keeps all work in Python background CLI jobs; a second code base is a long-term cost for a one-person project.
- No evasion of bot controls (PRD §4.3): the route must not depend on hiding automation.
- Spike S-1 (2026-11-01): Playwright 1.64.1 drives Edge 156 headed through `channel="msedge"` with a persistent dedicated profile; Edge's "Save your password?" prompt appears for Playwright-filled forms and saves locally once accepted; `--disable-sync` is the only default flag that blocks sync.

## Decision

Use Playwright for Python, `launch_persistent_context(channel="msedge", headless=False)` on a JobScraper-owned profile at `%LOCALAPPDATA%\JobScraper\apply-profile`, with Playwright's default arguments. Drop `--disable-sync` only behind `apply.edge_sync` after the owner's sync test. All input goes through a small set of primitives in `apply/browser.py` with read-back checks.

## Options Considered

### Option A: Playwright + dedicated Edge profile (chosen)
| Dimension | Assessment |
|---|---|
| Complexity | Low–medium: Python, same process model as runs |
| Cost | Free; uses the installed Edge, no browser download |
| Robustness | High: full API, file upload, waits, screenshots |
| Familiarity | Python, as the rest of the app |

**Pros:** stays in the layering; proven by career-ops; screenshots and HTML evidence are easy; one attempt at a time fits the job runner.
**Cons:** passwords Edge saves land in the app profile, not Default (bridged by ADR-0002); `navigator.webdriver` may raise CAPTCHA rates (the attempt then fails honestly).

### Option B: CDP attach to the owner's running Default Edge
**Cons:** blocked on the default profile in Chromium 136+; Playwright warns against it. Rejected.

### Option C: MV3 extension in the Default profile, talking to the local API
| Dimension | Assessment |
|---|---|
| Complexity | High: TypeScript extension, sideloading, page-injected scripts for React inputs |
| Cost | A second code base |

**Pros:** real profile, Edge's own password manager and autofill, lowest bot signal.
**Cons:** large build; file upload via synthesized `DataTransfer`; harder screenshots and evidence. Revisit in M22 only if the password bridge proves unworkable (PRD §4.2).

### Option D: extension using `chrome.debugger`
**Cons:** as C plus a visible "being debugged" banner. Rejected.

## Trade-off Analysis

A buys a fast, testable, Python-only build at the price of a separate browser profile. The profile split matters only for passwords, which ADR-0002 handles with the keyring as the source of truth. C's advantages are real but cost a second code base for a feature whose hard parts (resolution, audit, fail-closed rules) are browser-agnostic.

## Consequences

- Easier: one language; adapters are plain Python; dry runs and fixtures with a local `http.server`.
- Harder: the owner must import passwords into Edge (CSV) unless sync works; the app profile is one more place where site cookies live.
- Edge shows an "unsupported flag --no-sandbox" bar (cosmetic).
- Only one process may use the profile: guaranteed by the single job slot.
- Revisit if: Playwright stops supporting branded Edge, CAPTCHA rates make attempts fail routinely, or the owner wants autofill in Default without imports (Option C).

## Action Items

1. [ ] Lane B builds `apply/browser.py` per `apply_design.md` §8.
2. [ ] Owner runs the S-1c sync test when convenient; set `apply.edge_sync` from the result.
3. [ ] Record R-3's outcome (Submit-time reCAPTCHA) after the M20 owner submission.
