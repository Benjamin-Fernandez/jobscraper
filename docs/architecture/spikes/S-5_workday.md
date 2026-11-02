# Spike S-5: Workday flow, signed-out part (Q-23, 2026-11-02)

**Author:** software-engineer (report placed by the architect, Q-35; source: `comms/outbox/software-engineer.md`, Q-23 entry). Branch `spike/Q-23-workday`.
**Public repo:** tenants are named by their Workday data centre only. **Tenant C (wd1)** and **tenant B (wd5)**; tenant B is the same tenant as in S-5b (`S-5b_llm_workday.md`). No employer name, requisition id, site name or personal value appears here.

## Scope and result

Two tenants, headed Edge (`msedge`), throwaway profiles, Playwright 1.64.1 defaults, no stealth flags. Signed out only: posting, Apply choice, Create Account form, Sign In form, one deliberately empty Sign In click (error markup), `<job_url>/apply/applyManually` opened directly, `/userHome` signed out. Nothing typed, no account created, no mail read, no Submit (the owner's direct go-ahead for real accounts came later, D-77; that part is S-5b). No CAPTCHA or bot check met. Both tenants behaved the same unless noted.

## Checklist (`apply_design.md` §9.4)

| # | Result |
|---|---|
| 1 | Confirmed. `adventureButton` = `<a role="button" href="<job_url>/apply">`; no `jobPostingApplyButton`. Dialog `div[role=dialog][data-automation-id="wd-popup-frame"][aria-label="Start Your Application"]`; items `<a role="button">` `autofillWithResume`, `applyManually`, `useMyLastApplication` (all offered signed out) plus `closeButton`; hrefs `<job_url>/apply/<choice>`. `<job_url>/apply/applyManually` opens the manual flow directly. |
| 2 | Confirmed with differences. The **Create Account form shows first**, as wizard step 1 "Create Account/Sign In", with the progress bar visible. Ids: `email`, `password`, `verifyPassword`, `createAccountCheckbox`, `createAccountSubmitButton`, `signInSubmitButton`; `createAccountLink` / `signInLink` are `<button>`s; `forgotPasswordLink`; form `signInFormo`; the checkbox container is `formField-` (empty name). The submit `<button>` is `aria-hidden="true" tabindex="-2"`; its **preceding sibling** `div[data-automation-id="click_filter"][role=button][aria-label=<button text>]` takes the click (a plain click on the button times out). Wrapper `noCaptchaWrapper` is not a captcha. Honeypot `input[data-automation-id="beecatcher"][name="website"]` ("for robots only"): never fill. Password rules: upper, lower, alphabetic, numeric, special, ≥ 8. The terms checkbox has no required marker. |
| 3, 4 | Not reached (signed out). |
| 5 | Progress titles: Create Account/Sign In, My Information, My Experience, Application Questions, Voluntary Disclosures, Review (both). Item text carries a "current step N of M " / "step N of M " prefix. Flow container `applyFlowPage`. Step containers not reached. |
| 6 | On the account forms: `formField-<name>`, `<label for><span>Text<abbr aria-hidden="true">*</abbr></span></label>`, `aria-required="true"`. |
| 7–10, 12 | Not reached. |
| 11 | Field errors: input `aria-invalid="true"` + `aria-describedby="error1-<id>"` → `<p data-automation-id="inputAlert"><span>Error: </span>…</p>`. No `errorMessage`, no banner, no `role=alert` (sign-in form). S-5b found the same markup on wizard steps. |
| 13 | Signed out, `/<locale>/<site>/userHome` → `/<locale>/<site>/login?redirect=…userHome` (sign-in form). Session-expired copy not met. |

Other: no captcha iframes, widgets or scripts on any page. Tenant B shows a cookie banner `legalNotice` (`legalNoticeAcceptButton` / `legalNoticeDeclineButton`). Tenant C's careers site says applications moved to another ATS; its Workday postings still open the apply flow (it was dropped as a gate employer, D-77). Posting ids for open/closed checks: `requisitionId`, `postedOn`, `timeLeftToApply`.

## Design differences (folded into `llm_fill_design.md` §3, §9.1)

- (a) The click overlay `click_filter` is the button's **sibling** `div[role=button]`, not its parent.
- (b) Field errors are `[data-automation-id="inputAlert"]` + `aria-invalid`; `errorMessage` did not appear.
- (c) `account_wall()`: the progress bar is visible on the account page, so the sign-in / create checks must win over "progress bar → no wall".
- (d) Progress titles need the "step N of M" prefix stripped.
- (e) The reader must skip `beecatcher` and cope with `formField-` (empty name).
- (f) A cookie-banner dismissal (decline) before Apply / Next.
