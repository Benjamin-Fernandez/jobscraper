# Stage-A brief: application status from email (Q-60 / F-50)

Researcher, 2026-11-02, branch `int/Q-60-mail-status`. Covers the access route, Gmail IMAP incremental sync, sender patterns, phrasing, prior art and terms. It is not a design: schemas and module plans are the architect's job.

**Evidence tags.** **F** = page fetched on 2026-11-02. **Sn** = seen only in a search-result snippet on 2026-11-02 (page not opened). **K** = prior knowledge, not re-checked this session (treat as unverified). **I** = inference. **O** = opinion. Sources [M1]–[M31] are listed at the end; all were accessed on 2026-11-02. No real address, name or message content appears here: senders are given as domains and local-part patterns.

---

## 1. Access route

| | (a) IMAP + app password | (b) Gmail API, OAuth desktop app (loopback) | (c) IMAP + XOAUTH2 |
|---|---|---|---|
| What the credential can do | The whole mailbox (K). JobScraper limits itself to EXAMINE and BODY.PEEK (`apply/mail.py` header) | `gmail.readonly`: read-only, enforced by Google. Classed as **restricted** (so are `gmail.metadata`, `gmail.modify` and `mail.google.com`; `gmail.labels` is non-sensitive) [M5 F] | Needs `https://mail.google.com/`: "The scope for IMAP, POP, and SMTP access". That is full access and restricted. No narrower IMAP scope exists for consumer accounts; Google says to move to the Gmail API for granular scopes [M7 F] |
| What it needs | 2-Step Verification on. Not offered with security-key-only 2SV, with Advanced Protection, or on work/school accounts [M1 F] | A Google Cloud project, the Gmail API enabled, an OAuth consent screen (External: "Internal" needs a Workspace org [M6 F]), a Desktop client, the owner as a test user (K) | As (b) |
| Status in 2026 | Still offered, but Google says "App passwords aren't recommended and are unnecessary in most cases". No deprecation notice found [M1 F]. IMAP has been always on since January 2025 (there is no toggle) [M2 F]. Plain-password "less secure apps" sign-in is gone: Workspace pages give two conflicting cut-off dates (14 Mar 2025 and 1 May 2025) and name app passwords as the remaining exception [M3 Sn] | Supported | Supported |
| How long it lasts | Until revoked. "We revoke your app passwords when you change your Google Account password" [M1 F] | External app in **Testing** status: the refresh token **expires after 7 days** [M4 F]. It also dies on a password change (Gmail scopes), after 6 months unused, on revocation, or when more than 100 tokens exist per account per client [M4 F]. In "In production" status while unverified, there is an unverified-app screen and a cap of 100 new users [M6 F], and (K, unverified) the token is not on the 7-day clock | Same as (b) |
| Verification | None | A restricted scope needs verification before public launch. Test or experimental builds are exempt "unless you decide to launch it to the public" [M6 F]. A security assessment applies "If you store restricted scope data on servers (or transmit)" [M5 F] | Same as (b) |
| In JobScraper today | Built and verified: D-52 (IMAP, app password in Credential Manager), D-72 (application mailbox); `apply/mail.py` | Not built. It would add OAuth client libraries (I) | Not built |
| Incremental sync | UIDs per mailbox (§2) | `users.history.list` from a stored `historyId` (K) | UIDs per mailbox |

**Recommendation (O): (a) IMAP with the existing app password.** It reads All Mail (found by `\All`) and Spam, read-only as today, headers first.

- **Why:** no new setup for the owner and no re-consent, where (b) in Testing needs a fresh consent every week. It reuses a path and code the owner has already verified (D-52, D-72), adds no new dependencies, and needs no Google Cloud project.
- **Trade-off accepted:** an app password is a full-mailbox credential, and Google discourages it. Read-only is enforced by JobScraper's own code (EXAMINE plus PEEK; never STORE, COPY, MOVE, EXPUNGE or APPEND; never SMTP), not by Google.
- **What breaks, and when:**
  1. The owner changes the Google password. The app passwords are revoked [M1], the login is refused, and F-50 should pause in the same "mail not set up" state the apply flow already uses. The owner then makes a new app password.
  2. The owner turns on Advanced Protection or security-key-only 2SV. App passwords are then unavailable [M1].
  3. Google withdraws app passwords for consumer accounts. No announcement has been found, but [M1]'s wording makes this a rising risk. The answer is to move to (b).
- **Fallback (b), documented but not built:** `gmail.readonly`, with the External app set to "In production" and left unverified so the token is not on the 7-day clock. That clock behaviour is unverified (§7). The owner clicks past the unverified-app screen once. Keeping the mail transport behind one boundary makes the swap local (O; the architect decides).
- **Reject (c):** it has the widest scope plus all of OAuth's setup and token life cycle, the worst of both (O).
- **Which mailbox:** start with the application Gmail (D-72). It receives only job mail, so the noise and the privacy exposure are small (I). Reading the owner's personal mailbox as well is a scope decision for the owner (§7).

## 2. Gmail IMAP incremental sync

**Facts**
- **UIDs.** Within a mailbox, UIDs rise strictly in arrival order and persist across sessions. If the server cannot keep them, it must raise UIDVALIDITY. The pair (UIDVALIDITY, UID) identifies a message in that mailbox. SELECT, EXAMINE and STATUS report UIDNEXT [M10 K, §2.3.1.1].
- **Gotcha:** `UID FETCH n:*` or `UID SEARCH UID n:*` always includes the highest UID, even when n is above it, because `*` means the largest UID in use [M10 K, §6.4.8]. Drop `uid <= last` on the client side, or compare UIDNEXT first.
- **Labels are folders.** Gmail "treats labels as folders for the purposes of IMAP", and each folder has its own UID space. **X-GM-MSGID** is a 64-bit ID that is the same in every folder (the decimal form of the web/API hex ID). **X-GM-THRID** is the Gmail thread. `FETCH X-GM-LABELS` returns the labels, UTF-7 encoded. **X-GM-RAW** runs Gmail web-search syntax inside SEARCH. Support is shown by the capability `X-GM-EXT-1` [M8 F].
- **Finding All Mail.** Gmail puts RFC 6154 special-use attributes on every LIST response: look for `\All`. Spam is `\Junk`; Sent and Trash have their own attributes. System labels use the prefix `[Gmail]` or `[GoogleMail]` [M8 F, M11 K], and some accounts show `[Google Mail]` (K). **Finding:** `apply/mail.py` hard-codes `"[Gmail]/Spam"` (`FOLDERS`, line 41), so on such an account Spam is silently skipped (I). The `\Junk` lookup fixes this.
- **When Gmail changes UIDVALIDITY:** Google doesn't document it; a search found nothing [M12 Sn]. Known causes (K) are deleting and recreating a label, renaming one, and rare server-side rebuilds. Treat any change as "the old UIDs no longer apply".
- **INBOX vs All Mail (K):** All Mail holds every message except Spam and Trash. That includes archived mail, mail that a filter sends past the inbox ("Skip the Inbox"), sent mail and drafts. Category tabs (Promotions, Updates and so on) are only a web view, and their mail is still in INBOX over IMAP. So INBOX alone misses archived and filtered mail (I). All Mail also returns the owner's own sent replies, which must be skipped: check for `\Sent` in X-GM-LABELS, or a From that is the account's own address (I).
- **Visibility settings.** The owner can hide a label, All Mail included, from IMAP ("Show in IMAP", K). Gmail can also limit IMAP to folders of 10,000 messages or fewer [M2 F]. Check at run time; if All Mail isn't listed, fall back to INBOX plus Spam and say so in the UI (I).
- **Read-only.** EXAMINE opens a mailbox read-only (no flag changes), and BODY.PEEK fetches without setting `\Seen` [M10 K]. `mail.py` already does both.
- **Header-only fetch.** Fetch `INTERNALDATE X-GM-MSGID X-GM-THRID X-GM-LABELS BODY.PEEK[HEADER.FIELDS (FROM REPLY-TO TO SUBJECT DATE MESSAGE-ID LIST-ID LIST-UNSUBSCRIBE AUTO-SUBMITTED)]` [M8 F, M10 K]. Fetch a body only for messages that pass the sender and keyword gate (I). `mail.newest_from` already uses this shape.
- **CONDSTORE/QRESYNC:** no Google document found [M12 Sn]. K: Gmail advertises CONDSTORE but not QRESYNC. Neither is needed, because F-50 only needs new arrivals, not flag changes (I).
- **SEARCH SINCE** compares dates only, ignoring time and timezone [M10 K]. Subtract a day and filter on INTERNALDATE, as `mail.py` already does.
- **Spam** is its own mailbox, outside All Mail (K), and ATS mail often lands there. Confirmations sent by Workday "frequently" go to spam [M15 Sn], and SuccessFactors mail can be flagged as spam when SPF doesn't match [M18 Sn]. A message the owner marks "Not spam" moves into All Mail with a new UID but keeps its X-GM-MSGID (I, from [M8]).
- **Limits.** Up to 15 email clients per account [M2 F]. Workspace accounts: 2,500 MB a day of IMAP download, and a suspension that "typically lasts for 1 hour, but can last up to 24 hours" [M9 F]. Consumer limits are not published (unverified). A header-only scan costs a few KB per message (I). Gmail also supports IDLE (K), but polling every few minutes while the app runs is enough (O). Use one connection and log out each time, because the apply flow's watcher also uses a client slot (I).

**Recommended cursor (O).** Keep one cursor per (account, mailbox role), with the role being `\All` or `\Junk`. Each holds:
1. the mailbox name last found by LIST (re-resolve it each run by special-use, because names are localised);
2. UIDVALIDITY;
3. the highest UID **fully processed**, advanced only after that message's outcome is stored;
4. the UTC time of the last successful scan.

Alongside these, keep one account-wide set of processed **X-GM-MSGIDs**. It dedupes across All Mail and Spam, across Spam-to-All-Mail moves, and across UIDVALIDITY resets.

Each run: EXAMINE. If UIDVALIDITY matches and UIDNEXT > last + 1, fetch headers for `last+1:*` and drop `uid <= last`. If UIDVALIDITY changed, rescan `SINCE (last scan − 1 day)`, dedupe by X-GM-MSGID, and store the new pair.

**First-sync window (O).** Start at the earliest `applied_at` among applications not yet in a final state, minus 1 day, but go back no more than 180 days. Rejections can arrive months later, and 180 days covers a graduate hiring cycle (I). Read headers only. Note UIDNEXT *before* the first scan so that mail arriving during the scan is picked up next run. Use X-GM-RAW only as a first-sync prefilter (for example `newer_than:180d` plus ORed sender domains), never as the cursor: its results aren't UID-ordered, and Gmail's search semantics can change (O).

## 3. Sender patterns

The From domain identifies the **platform, not the employer** (I). The employer and the role come from the display name, the Workday tenant local part, Reply-To, the subject and the body. Many employers also send from their own domain (recruiter mail, or custom sending domains). So match the employer's registrable domain as well; `apply_design.md` §11.3 already derives it.

| Platform | Sender domain(s) | Where employer and role appear | Evidence |
|---|---|---|---|
| Greenhouse | `no-reply` at `us.greenhouse-mail.io`, `eu.greenhouse-mail.io`, `greenhouse.io`, `anz.greenhouse.io` [M13]. Job-board confirmation pages say the mail "will likely be" from the `us.greenhouse-mail.io` one [M14]. Recruiters may write from their company address (K) | Display name usually the company (K). Subject and body come from templates carrying company and job-name tokens (K) | Sn / K. The security-code mail (D-85) comes from the same domains: exclude it |
| Workday | `<tenant>@myworkday.com`: the local part is the employer's tenant [M15]. Reply-To is configured per tenant [M16]. Some employers send no confirmation at all [M17] | Display name "<Employer> …"; the tenant local part ≈ the employer; the role is in the subject or body, depending on the template (K) | Sn. Account verification and password mail come from the same domain: exclude |
| Lever | `hire.lever.co` (no-reply plus per-recruiter relay addresses) | Recruiter or company display name; subject often "<Company> – <role>" | K |
| Ashby | `ashbyhq.com`; custom domains possible | Company display name | K |
| SmartRecruiters | `smartrecruiters.com` by default; employers can authenticate their own sending domain [M19] | Display name, body | Sn |
| SAP SuccessFactors | Local part `system` at `successfactors.com` or `successfactors.eu`, by data centre. With "Single Sender": `correspondence<CompanyID>@<x>.successfactors.com` [M18]. Or the employer's domain | Display name, body | Sn |
| Oracle Taleo / Recruiting Cloud | Taleo: `taleo.net` (K). Oracle Cloud: an `oraclecloud.com` host (K). Oracle advises not to change a default `invalidemail.com` sender-domain setting [M20] (exact effect on candidate mail unclear) | Often a generic "status changed, log in" notice (K) | Sn / K |
| iCIMS | `icims.com`, or the employer's domain | Body | K |
| Eightfold | `eightfold.ai`, often the employer's domain | Body | K |
| Phenom | `phenom.com` / `phenompeople.com`; mostly talent-community and job-alert mail | Body | K |
| HackerRank | `hackerrankforwork.com`, `hackerrank.com` (K); templates put the company name in the subject [M22] | Subject, body | Sn / K |
| Codility | `codility.com` (K); Codility sends the invite on the employer's template [M21] | Body (company, test name) | Sn / K |
| CodeSignal | `codesignal.com` | Body | K |
| HireVue | `hirevue.com` | "<Company> has invited you to …" | K |
| SHL | `shl.com` | Body | K |
| Harver / pymetrics | `harver.com`, `pymetrics.com` / `pymetrics.ai` | Body | K |
| Mercer Mettl | `mettl.com` | Body | K |
| TestGorilla | `testgorilla.com` | Body | K |
| Job boards (noise) | LinkedIn `linkedin.com`; Indeed `indeed.com` (employer replies relayed through `indeedemail.com`); JobStreet/SEEK; MyCareersFuture; Glassdoor | Alerts and "application viewed/sent" notices | K |

Assessment invites come from vendor domains that no tracked application points at, so tying one to an application depends on the company name in the subject or body (I). Lookalike assessment and offer mail is a known scam vector [M30 Sn]. F-50 should never open links (O).

## 4. Phrases per category

These phrases are high precision only **after two gates** (I):
1. the sender is an ATS or vendor domain, or the employer's registrable domain;
2. the message is not bulk mail. `List-ID`, `Precedence: bulk`, several job titles in one message, or alert wording push it to "not a status". `List-Unsubscribe` is only a weak signal, because some transactional mail carries it too.

All phrases are case-insensitive.

| Category | High-precision phrases | Low precision: never use alone | Evidence |
|---|---|---|---|
| 1. Acknowledged / applied | "thank you for applying", "thank you for your application", "we have received your application", "your application has been received", "application received", "we confirm that your application has been received", "successfully submitted" | "thank you for your interest" (also opens rejections), "next steps" | [M14 Sn], [M23 F], K |
| 2. Assessment invite | "invited you to (take\|complete) (an\|the) (online )?assessment", "online assessment", "coding (challenge\|assessment\|test)", "complete the assessment by", "assessment invitation", "game-based assessment", "on-demand / digital video interview" (HireVue: see §7 on mapping) | "assessment" or "test" alone (job descriptions, newsletters) | K / I |
| 3. Interview | "invite you to (an\|a) interview", "interview invitation", "schedule (an\|your) interview", "select a time", "your availability for an interview", "interview confirmation", "phone screen", "first-round interview"; a `text/calendar` part with `METHOD:REQUEST` (K) | "interview" alone (tips mail, HireVue), "next steps", "schedule a call" (sourcing mail) | [M23 F], K |
| 4. Rejected | "decided not to move forward", "will not be moving forward", "move forward with other candidates", "pursue other candidates", "not been successful", "unsuccessful on this occasion", "we regret to inform you", "not be progressing your application", "position has been filled" | "unfortunately" (also in acknowledgement volume disclaimers and reschedule mail), "after careful consideration", "thank you for your interest" | [M23 F], [M29 Sn], K |
| 5. Offer | "pleased to offer you", "delighted to offer you", "offer of employment", "letter of offer" (common Singapore wording, K), "offer letter", "employment contract" | "congratulations" (assessment completions, newsletters), "compensation" | [M23 F], K |
| 6. Withdrawn / posting closed | "your application has been withdrawn", "you have withdrawn", "the position has been (closed\|cancelled\|put on hold)", "no longer accepting applications", "requisition has been closed" | "closed" alone | K |
| 7. Kept on file / talent pool | "keep your (resume\|CV\|details\|profile) on file", "added to our talent (pool\|community)", "consider you for future (opportunities\|roles)", "should a suitable role arise" | Usually comes with a rejection. Together with a category-4 phrase → rejected. Alone in a "welcome to our talent community" mail → no change | [M29 Sn] |

**Tricky cases** (I unless tagged):
- **Neutral subjects.** "An update on your application" and "Your application status" carry no polarity, so classify from the body. If the body only says "log in to view" (a portal notice, common for Workday, SuccessFactors and Taleo, K), the result is "update, unknown" for the owner to check. Never guess.
- **Volume disclaimers.** An acknowledgement may say "unfortunately … we cannot guarantee individual replies" ([M14 Sn] shows the pattern). It is still an acknowledgement.
- **Talent-community newsletters and employer job alerts** come from the same ATS domains (Workday, Phenom, Eightfold) as status mail. "Talent community", "job alert", "jobs you may like", "recommended jobs", "new jobs matching" and lists of several job titles mean not a status.
- **Job-board mail** (LinkedIn, Indeed, JobStreet, MyCareersFuture and Glassdoor alerts, and "your application was viewed/sent") is not a status for tracked ATS applications. Job boards are out of scope as targets (`01_scope_and_goals.md` §6).
- **Verification, security-code, account-created and password-reset mail** (`mail.py` `VERIFY_WORDS`; D-85) is an "account" class: never a status, and never consumed a second time. Note that `VERIFY_WORDS` contains "confirm", which also appears in acknowledgements ("this email confirms …"). Decide by whether a code or link is present, not by the bare word.
- **Reschedules, cancellations and reminders** ("rescheduled", "your assessment expires in …", "thank you for completing") leave the stage unchanged.
- **Recruiter outreach** ("came across your profile") is not about a tracked application.
- **Auto-replies** (`Auto-Submitted: auto-replied`, RFC 3834, K) and the owner's own sent mail inside All Mail: skip both.
- **Out-of-order mail.** A late acknowledgement after a rejection must not move the status backwards. Prior art puts any demotion behind owner approval [M26 Sn].
- **One employer, several applications.** The role title must match; if it doesn't, the case is ambiguous (O: don't auto-update).
- **Scams.** Fake offers and assessments exist [M30 Sn]. Accept an offer only from an ATS or employer domain, in a thread that can be tied to an application (O).
- **Non-English mail** (for example Chinese, from regional employers) goes to the LLM tier or "unknown".

## 5. Prior art (details and links in `prior_art.md`, section Q-60)

| Project | Licence | Activity | Approach | Verdict |
|---|---|---|---|---|
| Xiangyahaian/offerflow | MIT | 222 stars; created and last pushed 2026-08-17 | Local-first; IMAP; AI extraction; SQLite (Chinese README) | **Learn from** |
| rutuu/ApplyTrail | MIT | 1 star, 5 commits | Gmail API read-only; keyword rules first, ambiguous → "unknown"; optional cloud-LLM fallback | **Learn from** (phrase seeds in §4) |
| mkhawam/AppTracker | none stated | 0 stars; last push 2025-05-04 | IMAP; Bayesian "is this job mail?" gate, then Ollama for status; MongoDB | **Learn from** the two-stage idea; no licence, so no code reuse |
| n8n "Job Status Analyser" template | unverified | — | Gmail API; Ollama Llama 3.1 8B; spam prefilter; demotions need one-tap approval | **Learn from** |
| OnlyJobs Desktop | MIT (per the SourceForge listing) | unverified | Electron; local Llama 3.2 3B; Gmail | **Learn from** (a small local model is workable) |
| 9 other Gmail-tracker repos | not checked | not checked | Mostly Gmail API with cloud LLMs, Sheets, Notion or Mongo | **Reject** for reuse |

There is nothing to reuse as a library: build on `apply/mail.py`. The patterns worth taking are:
- deterministic rules first, with an explicit "unknown" bucket (this matches principle 3);
- a cheap job-mail gate before any LLM call;
- owner approval before any downgrade;
- normalising company names when matching.

## 6. Terms

- IMAP is a standard Gmail feature and always on [M2 F], and app passwords exist for exactly this kind of client [M1 F]. No Google term was found that forbids an owner's own script reading the owner's mailbox (I). The Google Terms of Service and Gmail Program Policies were not re-read this session (K).
- If route (b) is ever used, the Google API Services User Data Policy and its Limited Use rules apply to restricted scopes ([M31] K, not fetched). Test builds that are not launched publicly are exempt from verification [M6 F]. The security assessment applies only when restricted-scope data is stored on or sent to servers [M5 F]; a local-only app keeps the data on the PC (I).
- Overuse limits lead to temporary suspension [M9 F]. The cap is 15 clients [M2 F].
- **Data (principle 6):** message text stays on the PC and only the local Qwen sees it. Recruiter names and addresses are third parties' personal data (I). Singapore's PDPA excludes individuals acting in a personal or domestic capacity (K, unverified). The public-repo rule still applies: no real mail in fixtures, and golden cases are synthetic.
- Never load remote images or follow links from mail: they can be tracking pixels or phishing (O).

## 7. Unverified and open items

1. The sender domains tagged K in §3 (Lever, Ashby, iCIMS, Eightfold, Phenom, Taleo/ORC and every assessment vendor) need confirming against real headers. Suggestion: with the owner's consent, the Coordinator runs a header-only count of From domains in the application mailbox. That is an S-4-style spike, and no content enters the repo.
2. Gmail behaviour: is CONDSTORE advertised? What changes UIDVALIDITY? Is All Mail visible (the owner's "Show in IMAP" setting and the 10,000-message cap)? Do category tabs appear in INBOX? Probe CAPABILITY and LIST at run time.
3. Route (b) only: is an unverified "In production" app with a restricted scope still allowed for one consumer user, and are its refresh tokens free of the 7-day expiry?
4. Consumer-account IMAP bandwidth limits are not published.
5. **Owner decisions:**
   - which mailboxes F-50 reads: the application Gmail only, or also the personal one, which holds older manual applications;
   - whether F-50 may set "offer" and "rejected" by itself, or only propose them.
6. **Architect decisions:**
   - whether HireVue one-way video counts as assessment or interview;
   - whether "posting closed" or "withdrawn" is its own state or counts as rejected;
   - how to treat "kept on file" when it appears alone.
7. Golden cases: none hand-checked yet. They need the real shapes from item 1; synthetic fixtures are then built from those shapes.
8. Finding for the architect: `apply/mail.py` hard-codes `[Gmail]/Spam` and should use the `\Junk` special-use lookup.

## Sources (all accessed 2026-11-02)

| ID | URL | Tag |
|---|---|---|
| M1 | https://support.google.com/accounts/answer/185833 | F |
| M2 | https://support.google.com/mail/answer/7126229 | F |
| M3 | https://knowledge.workspace.google.com/admin/sync/transition-from-less-secure-apps-to-oauth | Sn |
| M4 | https://developers.google.com/identity/protocols/oauth2 | F |
| M5 | https://developers.google.com/workspace/gmail/api/auth/scopes | F |
| M6 | https://support.google.com/cloud/answer/7454865 | F |
| M7 | https://developers.google.com/workspace/gmail/imap/xoauth2-protocol | F |
| M8 | https://developers.google.com/workspace/gmail/imap/imap-extensions | F |
| M9 | https://knowledge.workspace.google.com/admin/gmail/gmail-bandwidth-limits (redirected from support.google.com/a/answer/1071518) | F |
| M10 | RFC 3501 https://www.rfc-editor.org/rfc/rfc3501 (same rules in RFC 9051) | K |
| M11 | RFC 6154 https://www.rfc-editor.org/rfc/rfc6154 | K |
| M12 | https://datatracker.ietf.org/doc/html/rfc5162 (QRESYNC; UIDVALIDITY mismatch handling); no Gmail-specific source found | Sn |
| M13 | https://support.greenhouse.io/hc/en-us/articles/17675865619099 | Sn |
| M14 | https://job-boards.greenhouse.io/givewell/jobs/4253692008/confirmation (and similar board confirmation pages) | Sn |
| M15 | https://hr.uw.edu/talent/hiring-process/workday-recruiting-job-aids/candidate-communications ; https://www.slhn.org/~/media/EA695A80FC0B4CE9ABCECC519C8AD19B.ashx | Sn |
| M16 | https://doc.workday.com/admin-guide/en-us/human-capital-management/recruiting/candidates/notifications-for-candidates/wwg1583498320976.html | Sn |
| M17 | https://www.loopcv.pro/guides/workday-application-submitted-no-email (third party) | Sn |
| M18 | SAP KBAs surfaced by search, e.g. https://userapps.support.sap.com/sap/support/knowledge/en/2805763 (the exact KBA holding the sender rule is not pinned) | Sn |
| M19 | https://learning.sap.com/courses/smartrecruiters-for-sap-successfactors-academy/configuring-email-domains | Sn |
| M20 | https://support.oracle.com/knowledge/Oracle%20Cloud/2633027_1.html | Sn |
| M21 | https://support.recruitee.com/en/articles/3119329-codility-integration | Sn |
| M22 | https://hackerrank-knowledge-base.help.usepylon.com/articles/9684438314 | Sn |
| M23 | https://github.com/rutuu/ApplyTrail | F |
| M24 | https://api.github.com/repos/Xiangyahaian/offerflow | F |
| M25 | https://api.github.com/repos/mkhawam/AppTracker | F |
| M26 | https://n8n.io/workflows/15299-automatic-workflow-to-categorise-your-job-status/ | Sn |
| M27 | https://dev.to/maninampally/how-i-built-an-ai-system-that-turns-gmail-into-a-job-tracker-2an5 | Sn |
| M28 | https://sourceforge.net/projects/onlyjobs-desktop | Sn |
| M29 | https://www.adaface.com/email-templates/job-application-rejection/ ; https://www.dice.com/recruiting/rejection-notice-samples-and-best-practices-for-recruiters ; https://factohr.com/letter/rejection-email-templates/ | Sn |
| M30 | https://builtin.com/articles/avoid-fake-job-scams | Sn |
| M31 | https://developers.google.com/terms/api-services-user-data-policy | K |

Internal: D-52, D-72, D-85 (`instructions/02_status.md`); `src/jobscraper/apply/mail.py`; `docs/research/auto_apply_brief.md` §5.
