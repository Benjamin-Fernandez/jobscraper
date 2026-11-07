# Outbox: coordinator

Only `coordinator` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD coordinator → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

### 2026-11-02 coordinator → architect, researcher, tester
TYPE: handoff
RE: Q-60 WP-R2 (header-only spike), F-50, mail_status_design §6.1/§7, MB §3/§7
BODY: Owner-approved header-only census of the application mailbox (read-only EXAMINE + BODY.PEEK[HEADER.FIELDS (FROM AUTHENTICATION-RESULTS AUTO-SUBMITTED LIST-ID)]; script and raw report kept outside the repo). Results, domains only: (1) LIST special-use present: \All="[Gmail]/All Mail", \Junk="[Gmail]/Spam", \Sent, \Trash. (2) Pre-login capabilities include X-GM-EXT-1 and IDLE; CONDSTORE not advertised (not needed). (3) 51 messages in All Mail, 0 in Spam; UIDVALIDITY and UIDNEXT reported for both. (4) Only 2 messages are from hiring platforms: myworkday.com (1) and an Oleeo sender `<employer>.tal.net` (1); the rest is non-job mail (accounts, retail, travel), which the header gate must skip unread. (5) Authentication-Results: every hiring-platform message has dkim=pass, spf=pass, dmarc=pass (2/2) → `require_auth: true` stands. (6) New platform for MB §3 and the rules file: Oleeo, `tal.net`, employer = first label of the sender subdomain written as one word (design amendment E1: `tenant_from_subdomain`). (7) The application mailbox is young: most of the owner's manual applications predate it, so F-50's first value comes from auto-apply mail; connecting the personal Gmail later is the owner's option (owner chose application mailbox first, 2026-11-02).
STATUS: open
