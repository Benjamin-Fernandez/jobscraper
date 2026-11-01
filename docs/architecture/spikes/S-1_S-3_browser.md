# Spike S-1 / S-3: driving the owner's Edge (Q-01, PRD R-1, R-3, D-53)

Date: 2026-11-01. Branch `spike/Q-01-browser`. Scratch artefacts (not committed; they contain desktop captures):
`C:/Users/Admin/AppData/Local/Temp/claude/C--Users-Admin-Documents-All-Created-Folders-Misc-Projects-JobScraper/2b77f614-4f7d-42d5-aa46-bdbe79bb4b94/scratchpad/spike-browser/` (called `$S` below).

Versions: Python 3.12.10, playwright 1.64.1, keyring 25.7.0 (backend `WinVaultKeyring`), Edge 156.0.4314.58 (Chromium 156.0.8078.80), Windows 11 26300. No `playwright install` was run.

## Summary

| Q | Answer |
|---|---|
| S-1a | Yes. `launch_persistent_context(channel="msedge", headless=False)` starts headed on Windows 11. |
| S-1b | Yes. Edge shows "Save your password?" and, once Save is clicked, lists the password in `edge://settings/autofill/passwords`, with Playwright's default flags and with the password/extension flags dropped; `fill` and `press_sequentially` both work. It is stored on the device only. |
| S-1c | The sign-in UI is available (Sign in button, Windows account offered). Whether sync actually runs could not be tested without signing in (owner task). Under default flags `--disable-sync` is present and the profile shows "Not syncing". |
| S-1d | `keyring` set/get/delete works; the entry is visible in `cmdkey /list` as `LegacyGeneric:target=jobscraper:spike`, user `test`. |
| S-1e | Import CSV: header `url,username,password` required; Chromium's own export adds `name` and `note`. Sourced second-hand (see below). |
| S-3 | Two real Greenhouse forms filled with dummy data (text, react-select, checkbox, resume upload); nothing submitted. reCAPTCHA Enterprise is present and invisible. |

## S-1a Launch and default args

Command: `python $S/s1a.py` (reads `edge://version`). Result: browser version 156.0.4314.58, headed window, screenshot `$S/s1a_version.png`, text `$S/s1a_edge_version.txt`.

Playwright's Chromium switches are defined in `playwright/driver/package/lib/coreBundle.js` (`chromiumSwitches`); the actual command line, confirmed in `edge://version`, is:

```
--disable-field-trial-config --disable-background-networking --disable-background-timer-throttling
--disable-backgrounding-occluded-windows --disable-back-forward-cache --disable-breakpad
--disable-client-side-phishing-detection --disable-component-extensions-with-background-pages
--disable-component-update --no-default-browser-check --disable-default-apps --disable-dev-shm-usage
--disable-edgeupdater --disable-extensions
--disable-features=AvoidUnnecessaryBeforeUnloadCheckSync,DestroyProfileOnBrowserClose,DialMediaRouteProvider,
  GlobalMediaControls,HttpsUpgrades,LensOverlay,MediaRouter,PaintHolding,ThirdPartyStoragePartitioning,
  BlockOriginHeaderModificationOnRedirect,AvoidCorsURLLoaderRestartOnRedirect,Translate,AutoDeElevate,
  OptimizationHints,NetworkTimeServiceQuerying,AimEnabled,msForceBrowserSignIn,msEdgeUpdateLaunchServicesPreferredVersion
--enable-features=CDPScreenshotNewSurface --allow-pre-commit-input --disable-hang-monitor
--disable-ipc-flooding-protection --disable-popup-blocking --disable-prompt-on-repost --disable-renderer-backgrounding
--disable-updater-scheduler --force-color-profile=srgb --metrics-recording-only --no-first-run
--password-store=basic --use-mock-keychain --no-service-autorun --export-tagged-pdf
--disable-search-engine-choice-screen --unsafely-disable-devtools-self-xss-warnings --edge-skip-compat-layer-relaunch
--disable-infobars --disable-sync --enable-unsafe-swiftshader --no-sandbox --user-data-dir=<dir>
--remote-debugging-pipe --flag-switches-begin --flag-switches-end
```

Notes:
- `--enable-automation` is NOT passed by this Playwright version.
- Relevant to passwords, sync and autofill: `--disable-sync` (the only one that blocks sync); `--password-store=basic` and `--use-mock-keychain` (keychain switches for macOS/Linux, no observed effect on Windows, where Chromium uses DPAPI); `--disable-extensions`, `--disable-component-extensions-with-background-pages`, `--disable-background-networking`, `--disable-component-update`; and the feature `msForceBrowserSignIn` (disabled, so Edge never forces sign-in).
- Side effect: with `--no-sandbox` Edge shows a bar "unsupported command-line flag: --no-sandbox" (visible in `$S/s1b_default_fill_desktop.png`). It does not affect the page.
- Settings shows "Managed by your organization" under these flags (cosmetic).

## S-1b Does Edge save a Playwright-filled password?

Setup: local form served by python `http.server` on 127.0.0.1:8791 (in-process, stopped at exit), `autocomplete="username"` / `"new-password"`, POST to `/welcome`. Script `$S/s1b.py <variant> <fill|type>`. The Save bubble is browser UI, so it was clicked through Windows UI Automation (`$S/clicksave.ps1`), which found exactly one "Save" button each time.

| Variant | Fill method | Save prompt shown | In `edge://settings/autofill/passwords` |
|---|---|---|---|
| default flags | `fill` | yes (`s1b_default_fill_desktop.png`) | yes, `http://localhost:8791`, 1 account (`s1b_default_fill_pwlist.png`) |
| default flags | `press_sequentially` (60 ms) | yes | yes (`s1b_default_type_pwlist.png`) |
| `ignore_default_args` dropping `--password-store=basic`, `--use-mock-keychain`, `--disable-component-extensions-with-background-pages`, `--disable-extensions`, `--disable-default-apps`, `--disable-background-networking`, `--disable-component-update`, `--disable-client-side-phishing-detection`, `--metrics-recording-only` | `fill` | yes | yes (`s1b_drop_fill_pwlist.png`) |
| same drop list | `press_sequentially` | yes | yes (`s1b_drop_type_pwlist.png`) |

`--disable-sync` was deliberately kept in the "drop" run (see S-1c: dropping it where Edge offers the Windows account could start syncing and pull the owner's data).

Conclusion: dropping flags is unnecessary; default flags already save passwords. The bubble says "will be saved to your device", so it is local only.

Caveats:
1. Playwright cannot see or click the Save bubble (not in the DOM). The app needs the owner to click Save, or Windows UI Automation as in `clicksave.ps1` (scoped to msedge processes whose command line contains the profile path), or it adds the entry on `edge://settings/autofill/passwords` (Add).
2. `edge://password-manager/passwords` is rejected by `page.goto` (`ERR_INVALID_URL`); `edge://wallet/passwords` redirects to the working URL `edge://settings/autofill/passwords`.
3. `inner_text` of that page is empty (shadow DOM); use screenshots.

## S-1c Sync in the Playwright profile

Evidence: `$S/s1c_profiles.png`, `$S/s1c_sync_page.png`. Nothing was clicked beyond opening Settings, and nobody was signed in.
- Settings > Profiles shows a "Sign in" button and the Windows account under "Sync this account" (and Google). The "Sync" row is greyed out until sign-in. So the sign-in UI is available under Playwright's flags.
- One fresh profile (the first launched) showed the Windows account already attached with "Not syncing" (Edge single sign-on from the OS). Behaviour varies between fresh profiles, so the app must not assume either state.
- Under default flags `--disable-sync` is on, so sync cannot run. A Playwright source comment says the flag avoids an `IdentityManager::HasPrimaryAccount` crash for ephemeral contexts; persistent contexts without it are untested.
- Unanswered: whether sync works with `ignore_default_args=["--disable-sync"]` after the owner signs in. Needs the owner.

Owner steps (script ready: `$S/owner_sync_test.py`, separate throwaway profile, `ignore_default_args=["--disable-sync"]`):
1. Run `python owner_sync_test.py`. In the Edge window open `edge://settings/profiles` and click Sign in with your Microsoft account.
2. Profile > Sync: turn Sync on and make sure Passwords is on.
3. Open `edge://settings/autofill/passwords`, click Add: site `https://spike.invalid`, user `spike-test`, password `SpikeTest!123`.
4. Wait about a minute. In your normal Edge (Default profile) open `edge://settings/autofill/passwords` and look for `spike.invalid`.
5. Present: the sync route works (drop `--disable-sync` for the app profile). Absent after 5 minutes: use the CSV route. Then delete the entry in both profiles and sign out of the test profile.

Privacy note: signing the app profile into the owner's account makes Edge download the owner's existing synced passwords into that profile, so `apply-profile` becomes a second place they are stored. Weigh this before choosing the sync route.

## S-1d keyring round trip

`keyring.set_password('jobscraper:spike','test',...)`, then `get_password` returned the value, and `cmdkey /list` showed `Target: LegacyGeneric:target=jobscraper:spike`, `Type: Generic`, `User: test` (`$S/s1d_out.txt`). After `delete_password`, `get_password` returned `None` and `cmdkey /list` had no `jobscraper` entry. A 1200-character secret also round-trips. Credential Manager blobs are limited (about 2.5 KB), so store only passwords, one entry per `jobscraper:<ats>:<tenant-host>` and email.

## S-1e Edge password import CSV (fallback route)

Export is not possible here. Sources (accessed 2026-11-01):
- https://github.com/gmanny/EdgePasswordImport : the header row must contain `url,username,password`.
- https://techcommunity.microsoft.com/t5/microsoft-edge-insider/importing-your-passwords-from-third-party-password-managers-to/ba-p/3719162 (Microsoft Community Hub; only the title could be retrieved) : import path is Settings > Profiles > Import browser data > Import from other password managers, then choose a `.csv`.
- A forum sample of an Edge export has the header `name,url,username,password,note`.

No authoritative Microsoft page listing the columns was found (the support URL tried returned 404). Recommended file: `name,url,username,password,note` (matches Chromium's export; extra columns are optional). The owner should verify with a one-row test import before relying on it.

## S-3 Greenhouse dry-run fill

Postings (from a copy of the DB, `companies.provider='greenhouse'`, open jobs): Vercel "Presentation Designer" `https://job-boards.greenhouse.io/vercel/jobs/6128387004`, and Dataiku "Senior Manager, Global Benefits" `https://job-boards.greenhouse.io/dataiku/jobs/6237419004`. Schemas fetched from `https://boards-api.greenhouse.io/v1/boards/<board>/jobs/<id>?questions=true`: `$S/gh_vercel.json`, `$S/gh_dataiku.json`. The apply form is on the posting page itself. Dummy data only (Test Applicant, test@example.com, one-page `dummy_resume.pdf`). No submit, no Enter key, pages closed after screenshots. Scripts `s3_probe.py`, `s3_fill.py`; log `s3_fill_log.txt`; screenshots `s3_<board>_loaded.png`, `_filled_top.png`, `_filled_full.png`; DOM dumps `s3_<board>_dom.json`.

Results (both boards):
- Text inputs: `locator("#first_name").fill(...)` etc. worked (values read back).
- Phone: an intl-tel-input widget. `#country` is the phone country selector (react-select, shows "+65"); `#phone` is `type=tel` and reformats the value ("9123 4567").
- react-select: works. Click `#id`, `press_sequentially(text, delay=60)`, wait for `.select__menu [role="option"]` filtered by the text, click it, and read the value back from the nearest `.select__control`. Gotcha: bare `[role="option"]` also matches about 249 hidden intl-tel-input items, so scope to `.select__menu`. The async "Location (City)" (`#candidate-location`) worked the same way.
- Checkbox (Dataiku GDPR consent): `check()` worked (`gdpr_processing_consent_given_1`).
- Resume: `page.set_input_files("#resume", pdf)` on the hidden `input[type=file]` worked; the file name appears on the page. Cover letter is `#cover_letter`.
- Not attempted: textarea questions (none required in these two) and multi-select.

Field-name mapping: the DOM element `id` equals the schema field `name` (`first_name`, `last_name`, `email`, `phone`, `resume`, `cover_letter`, `question_<id>`, and `gdpr_*_consent_given_1` for checkboxes, which also carry `name`). The `name` attribute is empty on other inputs. EEO/demographic fields have numeric ids (`4015790004`, `4000563004`) matching the schema's `demographic_questions`/`compliance`. Form elements not in `questions`: `#country` (phone country), `#candidate-location` (from `location_questions`), and an unnamed `remix-css-...-requiredInput` text input beside each required react-select (ignore it). Types: `multi_value_single_select` is a react-select; `input_text` is a plain input; `input_file` is a hidden file input.

reCAPTCHA: present on both. `iframe[src*="recaptcha"]` count 1 with `size=invisible` in its URL (`recaptcha.net/recaptcha/enterprise/anchor?...&size=invisible`), `.grecaptcha-badge` count 1, script `recaptcha/enterprise.js?render=<site key>`. No challenge (`bframe`) iframe appeared after filling. The score is only evaluated at Submit, which was not clicked, so Submit-time behaviour is unproven.

## Design implications

1. Launch with `launch_persistent_context(user_data_dir=%LOCALAPPDATA%\JobScraper\apply-profile, channel="msedge", headless=False)` and Playwright's defaults. Add `ignore_default_args=["--disable-sync"]` only if the owner's sync test passes and the owner accepts the privacy note. Keep all other flags.
2. Passwords: Edge saves them locally with default flags, so keyring stays the source of truth. The sync route is unproven (needs the owner test). Until then plan the CSV route (F-35 fallback): "Export new passwords for Edge" as `name,url,username,password,note`, plus "Copy password"; validate with a one-row import. Auto-clicking the Save bubble via UI Automation is possible but fragile; treat it as best effort.
3. react-select helper: the click, type, click-option sequence above, scoped to `.select__menu`, with a read-back check; never press Enter.
4. Field mapping: fetch the `?questions=true` schema, build the plan keyed by schema `name`, and address elements with `[id="<name>"]` (handles numeric ids). Handle the non-schema `#country` and `#candidate-location` separately. Re-read values after each fill.
5. CAPTCHA detection (F-38): stop only when a challenge is visible: `iframe[src*="bframe"]`, `iframe[title*="recaptcha challenge"]`, hCaptcha or Turnstile iframes. The invisible anchor iframe and `.grecaptcha-badge` exist on every Greenhouse board and are not blockers.
6. Open risk: R-3 stays partly open until a real owner-triggered submission shows how the invisible reCAPTCHA scores (M20 acceptance).
