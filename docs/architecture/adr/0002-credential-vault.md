# ADR-0002: Windows Credential Manager is the password vault; Edge gets passwords by CSV import (or sync)

**Status:** Accepted
**Date:** 2026-11-01
**Deciders:** architect; Coordinator at stage E
**Relates to:** PRD F-35, F-36, F-40, NF-02, D-52, D-57; `apply_design.md` §10, §11; spike `spikes/S-1_S-3_browser.md` (S-1b, S-1d, S-1e)

## Context

Automatic account creation (D-57) on Workday-style sites creates one password per employer tenant. The IMAP app password (D-52) is a full-mailbox credential. The repo is public; secrets must never reach SQLite, YAML, logs or prompts (NF-02). The owner wants passwords to be usable from their normal Edge.

Facts: `keyring` 25.7 on Windows uses `WinVaultKeyring` and round-trips entries (visible as `LegacyGeneric:target=jobscraper:<…>`), blob limit ~2.5 KB (S-1d). Edge's password database is protected by app-bound encryption; writing it is malware technique and out of scope (PRD §4.3). Edge imports a CSV whose header contains `url,username,password` (S-1e, second-hand). Edge's Save prompt works in the Playwright profile but is browser UI that Playwright cannot click (S-1b). Sync from the app profile is untested (S-1c).

## Decision

1. **Source of truth:** Windows Credential Manager through `keyring`, one entry per `jobscraper:<ats>:<tenant-host>` with user = email, and `jobscraper:imap:<host>` for the mailbox. A foundation module `vault.py` is the only code that reads or writes them.
2. **Write before use:** a generated account password is stored and read back **before** the sign-up form is submitted.
3. **DB records existence only:** `ats_accounts` holds ATS, tenant, email, status, dates; never a password.
4. **Into Edge, default:** "Export new passwords for Edge" writes `data/edge_passwords_<stamp>.csv` (`name,url,username,password,note`), the owner imports it, the app deletes it on confirmation and sweeps leftovers older than an hour.
5. **Into Edge, optional:** with `apply.edge_sync: true` (after the owner's sync test) the app profile syncs to the owner's account; a best-effort UI Automation click on Edge's Save prompt (`apply.edge_save_bubble`) may add the password there. Failure changes nothing: the keyring keeps it.
6. **Never:** reset a password, write `Login Data`, store a password in any file except the transient CSV.

## Options Considered

### Option A: keyring vault + CSV import / optional sync (chosen)
| Dimension | Assessment |
|---|---|
| Complexity | Low: `keyring` + `secrets`; CSV writer |
| Security | Per-Windows-user encryption (DPAPI); plaintext only in the transient CSV |
| Owner effort | One import per batch of new accounts (or none with sync) |

**Pros:** supported OS store; scriptable; visible to the owner in Control Panel; no new service.
**Cons:** the CSV is plaintext while it exists; SSD wear-levelling defeats secure delete (warned in UI).

### Option B: Edge only (owner saves each password by hand)
**Cons:** the app could not sign in on later attempts without asking the owner; contradicts D-57's full automation. Rejected.

### Option C: passwords in the app's DB or YAML (encrypted with an app key)
**Cons:** key management in a public-repo app; violates NF-02. Rejected.

### Option D: write Edge's `Login Data`
**Cons:** defeats app-bound encryption; infostealer technique; out of scope. Rejected.

## Trade-off Analysis

A keeps the only durable copy in a supported, OS-protected store and treats Edge as a convenience copy. The CSV's plaintext window is the main cost; it is short, owner-initiated, inside gitignored `data/`, and swept automatically. Sync would remove that window but copies the owner's existing synced passwords into the app profile (spike privacy note), so it stays opt-in.

## Consequences

- Easier: sign-in on later attempts is automatic; the web app can offer "Copy password" (foundation module, no stage import).
- Harder: Edge has the password only after an import (or sync); losing the Windows user profile loses the vault (owner backs up via Edge import or Credential Manager backup).
- `login_failed` "account exists but no password" needs a manual path: "Add an account you already have" in Settings.
- Revisit if: S-1c sync works and the owner accepts the privacy note (flip `edge_sync`), or Edge removes CSV import (fall back to Copy password only).

## Action Items

1. [ ] M21 lane V builds `vault.py` per `apply_design.md` §10.
2. [ ] Owner verifies the CSV format with a one-row import on the first export.
3. [ ] Owner task Q-14: Gmail app password into Credential Manager (`apply_design.md` §11.4).
