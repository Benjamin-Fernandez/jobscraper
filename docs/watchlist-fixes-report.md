# Watchlist feed fixes: research report (2026-09-24)

Covers the 59 companies whose feed failed in the last full cycle. Nothing in
`config/watchlist.yaml`, `data/`, `src/` or `tests/` was changed.

**Result: 22 VERIFIED, 30 not verifiable, 7 recommend disable.**

## How candidates were verified

`verify.py` (in this folder) builds `WatchedCompany(id=1, key, name, careers_url, provider, slug, feed_url)`
and calls `pipeline.fetch_one(pipeline.make_client(load_config()), company)`. It runs from the repo root, so
the real config, user agent, rate limit and robots.txt handling apply. A candidate is VERIFIED only when
`ok=True` and postings > 0. Every attempt, including the failed ones, is logged in `results.jsonl`, and the
fetched titles, locations and URLs are saved in `jobs/<key>__<provider>.json`.

- "SG" counts postings whose location or title contains "Singapore". It undercounts when Workday shows a
  multi-location job as "2 Locations".
- Workday and Workable feeds stop at `MAX_JOBS = 600`, so a count of "600" means the feed was truncated.
- The `generic_html` feeds are Singapore-filtered search pages. Their postings have no location, and only the
  first results page is read.

## Decisions for you

1. **UOB location label.** UOB's Workday tenant labels Singapore roles "Central Region (City Area)" (310 of
   600). `rules.yaml` → `location_explicit` has `allow_tokens: [singapore, sg]`, and a location that names
   anywhere else is rejected. As things stand, every UOB Singapore job would be filtered out. Either add an
   allow token such as `central region (city area)` or accept the loss. Nothing else in the verified set
   needed this. Wells Fargo uses "CENTRAL SINGAPORE" and OCBC uses "OCBC Singapore", and both already pass.
2. **600-posting cap on large Workday tenants.** GlobalFoundries, NXP, Micron, Morgan Stanley, Visa, OCBC,
   UOB and Wells Fargo all hit `MAX_JOBS`. Singapore postings beyond position 600 in Workday's default order
   are never seen. OCBC, Micron and GlobalFoundries are hit hardest. Changing this means a code change
   (a higher cap, or a Workday location facet), which is outside this task.
3. **Noise links from generic_html.** On NCS, CA-CIB and Nomura, `generic_html` also returns 4 to 8
   navigation links (for example "Trustwave" and "View All Jobs") alongside the real jobs. They have no
   location, so the filter passes them on to the model. Accept this, or skip those three.
4. **Duplicates and acquisitions (7 to disable).** VMware duplicates the Broadcom feed. Deribit is now
   Coinbase and Currencycloud is now Visa, and both parents are watched. HashiCorp jobs now live on IBM's
   careers site, and IBM is watched. Tokopedia now sits under TikTok (Bytedance is watched) and its Workable
   board is empty. Groq's Gem board is empty and Gem has no adapter. JD.com only hires in China. Pointing a
   duplicate key at its parent's feed would store every posting twice, so disabling is cleaner.
5. **Adapters that would unlock several of the 30 unverifiable companies.** These are ideas, not done:
   - **Oracle Cloud HCM** (CandidateExperience REST): CIMB, Akamai, Fortinet.
   - **Eightfold** (`/api/apply/v2/jobs`): Qualcomm, STMicroelectronics.
   - **Sea's in-house career API** (all client-rendered): Shopee, Garena, Monee.

## All 59 companies

Status key: **VERIFIED** = a proposed entry is in `watchlist_fixes.proposed.yaml`. **UNVERIFIABLE** = no
source the current adapters can fetch (reason given). **DISABLE** = recommend `enabled: false`.

### Dead hostnames (DNS)

| key | problem | what I found | status | sources |
|---|---|---|---|---|
| broadcom | careers.broadcom.com NXDOMAIN | Workday `broadcom.wd1/External_Career`: 371 postings, 31 SG | **VERIFIED** | hint + fetch |
| vmware-broadcom | careers.vmware.com NXDOMAIN | VMware is part of Broadcom. Its roles are on the Broadcom Workday above | **DISABLE** (duplicate of `broadcom`) | broadcom.wd1.myworkdayjobs.com |
| credit-agricole-cib | careers.ca-cib.com NXDOMAIN | Talentsoft list at jobs.ca-cib.com, filtered to Singapore: 7 SG vacancies + 8 nav links | **VERIFIED** (generic_html) | https://jobs.ca-cib.com/Pages/Offre/ListeOffre.aspx?mode=list&lcid=2057&facet_Country=169&showSearchUrl=1 |
| garena | careers.sea.com NXDOMAIN | career.sea.com sends Garena applicants to careers.garena.com, which is client-rendered (`/sg/jobs` returns 404) | UNVERIFIABLE: custom SPA, would need a Sea adapter | https://career.sea.com/ |
| sea-money-monee | careers.sea.com NXDOMAIN | Monee jobs are at careers.monee.com/careers, which is client-rendered (0 job links) | UNVERIFIABLE: custom SPA | https://careers.monee.com/careers |
| shopee-sea-group | careers.sea.com NXDOMAIN | careers.shopee.sg/jobs is client-rendered (0 job links). career.sea.com/jobs only gives 4 nav links, so it was rejected as a false positive | UNVERIFIABLE: custom SPA | https://careers.shopee.sg/jobs |
| globalfoundries | careers.globalfoundries.com NXDOMAIN | Workday `globalfoundries.wd1/External`: 600 (capped), 117 SG | **VERIFIED** | hint + fetch |
| gojek-goto | gotogroup.com NXDOMAIN | Lever `GoToGroup`: 35 postings, 12 SG (Lever `gojek` returns 404) | **VERIFIED** | https://jobs.lever.co/GoToGroup |
| tokopedia-goto | gotogroup.com NXDOMAIN | Workable `tokopedia` exists but has 0 postings. Lever `tokopedia` returns 404. Tokopedia is now majority-owned by TikTok, and GoTo roles are covered by `gojek-goto` | **DISABLE** | https://apply.workable.com/tokopedia/ |
| nxp-semiconductors | careers.nxp.com NXDOMAIN | Workday `nxp.wd3/careers`: 600 (capped), 8 SG | **VERIFIED** | hint + fetch |

### Transient errors (timeouts / 429)

| key | problem | what I found | status | sources |
|---|---|---|---|---|
| hcltech | timeout | hcltech.com/en-sg/careers/job-openings timed out again for our client. No ATS feed found (careers.hcltech.com is in-house) | UNVERIFIABLE: site times out, no public ATS. Retry later | https://www.hcltech.com/en-sg/careers/job-openings |
| hashicorp | 429 | hashicorp.com/jobs now says "View open positions" and links to `ibm.com/careers/search?q=hashicorp`. There is no separate board any more | **DISABLE** (covered by the `ibm` entry) | https://www.hashicorp.com/jobs |
| jd-com | transient | job.jd.com is a Chinese-language SPA. No international ATS found, and no Singapore hiring seen | **DISABLE** (not investigated further: China-only hiring) | - |
| maybank | transient | Careers now link to maybankjobs.com, a client-rendered SPA that timed out for our client | UNVERIFIABLE: SPA, no public ATS found | https://maybankjobs.com/ |
| morgan-stanley | transient | Workday `ms.wd5/External`: 600 (capped), 7 SG | **VERIFIED** | https://ms.wd5.myworkdayjobs.com/External |
| stmicroelectronics | transient | Jobs are on Eightfold (`stmicroelectronics.eightfold.ai`). No adapter | UNVERIFIABLE: Eightfold | https://stmicroelectronics.eightfold.ai/careers?location=Singapore |
| visa | transient | Workday `visa.wd5/Visa`: 600 (capped), 51 SG. The SmartRecruiters `Visa` board is empty | **VERIFIED** | https://visa.wd5.myworkdayjobs.com/Visa |

### Gone (404)

| key | problem | what I found | status | sources |
|---|---|---|---|---|
| bitmex | 404 on bitmex.com/careers | Greenhouse `bitmex` is the official board but has 0 postings today. If wanted later: `provider: greenhouse`, `slug: bitmex` | UNVERIFIABLE: correct board, currently empty | https://job-boards.greenhouse.io/bitmex |
| cimb | 404 | Singapore jobs are on Oracle Cloud HCM (`ejox.fa.ap1.oraclecloud.com` .../sites/CX_6). No adapter | UNVERIFIABLE: Oracle HCM | https://ejox.fa.ap1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_6/jobs |
| klarna | Lever `klarna` 404 | Klarna moved to Deel (`jobs.deel.com/job-boards/klarna`), which is client-rendered (0 links). Greenhouse and Ashby return 404, and SmartRecruiters and Workable are empty. Little Singapore presence | UNVERIFIABLE: Deel, no adapter. Consider disabling | https://www.klarna.com/careers/ |
| kredivo | 404 | Kredivo moved to careers.kredivocorp.com, which returns 403 to our scraper. Greenhouse, Lever and Ashby all return 404 | UNVERIFIABLE: blocked | https://careers.kredivocorp.com/ |
| mediatek | 404 | careers.mediatek.com/en/jobs is an SPA (in-house eREC, 1 nav link) | UNVERIFIABLE: SPA | https://careers.mediatek.com/en/jobs |
| uob | 404 | Workday `uobgroup.wd3/UOBExternal`: 600 (capped). Singapore roles are labelled "Central Region (City Area)" (310) | **VERIFIED** (see decision 1) | https://uobgroup.wd3.myworkdayjobs.com/UOBExternal |
| workday | 404 | Workday `workday.wd5/Workday`: 370 postings, 4 SG | **VERIFIED** | https://workday.wd5.myworkdayjobs.com/Workday |
| ifast | 404 | careers.ifastcorp.com/careers?region=sg is an SPA (0 links). The old job-openings.tpl page redirects there | UNVERIFIABLE: SPA | https://careers.ifastcorp.com/careers?region=sg |

### No job links found (generic_html)

| key | problem | what I found | status | sources |
|---|---|---|---|---|
| alibaba-alicloud | 0 links | Chinese-language SPA. No international ATS feed found | UNVERIFIABLE: SPA | - |
| ant-group | 0 links | Ant International (Singapore HQ) jobs are at ant-intl.com/en/job-search/, backed by the talent.antgroup.com SPA | UNVERIFIABLE: SPA | https://www.ant-intl.com/en/career/ |
| currencycloud | 0 links | Acquired by Visa (2021). No own board: Greenhouse, Lever and Ashby all return 404 | **DISABLE** (covered by `visa`) | - |
| deribit | 0 links | Acquired by Coinbase. No own board. Coinbase's Greenhouse has 213 postings, 7 SG, and is already watched | **DISABLE** (covered by `coinbase`) | https://job-boards.greenhouse.io/coinbase |
| groq | 0 links | Groq uses Gem (`jobs.gem.com/groq`), which has no adapter and 0 open roles. No Singapore presence | **DISABLE** | https://jobs.gem.com/groq |
| huawei | 0 links | Chinese campus SPA. No public ATS feed found | UNVERIFIABLE: SPA | - |
| meituan | 0 links | careers.meituan.com is an SPA. No ATS found for Keeta, its international arm | UNVERIFIABLE: SPA | - |
| netease | 0 links | NetEase Games' international Greenhouse `neteasegames`: 30 postings, 23 SG | **VERIFIED** | https://job-boards.greenhouse.io/neteasegames |
| ocbc | 0 links | Workday `ocbc.wd102/External`: 600 (capped), 363 SG | **VERIFIED** | https://ocbc.wd102.myworkdayjobs.com/External |
| tencent | 0 links | careers.tencent.com is an SPA backed by a private JSON API | UNVERIFIABLE: SPA | https://careers.tencent.com/en-us/home.html |

### Blocked (403): only an official public ATS feed was looked for

| key | problem | what I found | status | sources |
|---|---|---|---|---|
| akamai | 403 | Oracle Cloud HCM (jobs.akamai.com, .../sites/CX_1). The Workday guess `akamai.wd1/akamai_careers` returned 422 | UNVERIFIABLE: Oracle HCM | https://jobs.akamai.com/en/sites/CX_1/jobs |
| ampere-computing | 403 | Jobvite (careers.amperecomputing.com) also returns 403 | UNVERIFIABLE: blocked | https://careers.amperecomputing.com/ |
| bnp-paribas | 403 | Jobs are listed only on group.bnpparibas (the blocked host). No separate ATS feed found | UNVERIFIABLE: blocked | https://group.bnpparibas/en/careers/all-job-offers/singapore |
| citadel | 403 | Jobs are only on citadel.com/careers/details/... Greenhouse `citadel` returns 404 | UNVERIFIABLE: blocked, no ATS | https://www.citadel.com/careers/details/software-engineer/ |
| citadel-securities | 403 | Same situation. Greenhouse `citadelsecurities` returns 404 | UNVERIFIABLE: blocked, no ATS | https://www.citadelsecurities.com/careers/open-opportunities/ |
| cognizant | 403 | careers.cognizant.com (blocked). The Workday tenant found (`collaborative.wd1`) belongs only to a subsidiary, Collaborative Solutions | UNVERIFIABLE: blocked | https://careers.cognizant.com/us-en/jobs/ |
| finastra | 403 | Workday `finastra.wd3/FINC`: 150 postings, 4 SG | **VERIFIED** | https://finastra.wd3.myworkdayjobs.com/FINC |
| fortinet | 403 | Oracle Cloud HCM (`edel.fa.us2.oraclecloud.com` .../sites/CX_2001) | UNVERIFIABLE: Oracle HCM | https://edel.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001/job/22713 |
| goldman-sachs | 403 | higher.gs.com, including the Singapore results page, is client-rendered (0 links) | UNVERIFIABLE: SPA | https://higher.gs.com/results?LOCATION=Singapore&page=1&sort=RELEVANCE |
| infosys | 403 | Workable board "Infosys Singapore & Australia": 200 postings, 116 SG | **VERIFIED** | https://apply.workable.com/infosys-singaporeand-australia/ |
| kuaishou | 403 | Kwai's international Workday `kwai.wd3/Kuaishou_External`: 45 postings, 4 SG | **VERIFIED** | https://kwai.wd3.myworkdayjobs.com/Kuaishou_External |
| lam-research | 403 | SuccessFactors search at opportunities.lamresearch.com, filtered to Singapore: 25 SG postings + 1 nav link. The Workday guess returned 422 | **VERIFIED** (generic_html) | https://opportunities.lamresearch.com/search/?q=&locationsearch=Singapore |
| marvell-technology | 403 | Workday `marvell.wd1/MarvellCareers`: 238 postings, 21 SG | **VERIFIED** | https://marvell.wd1.myworkdayjobs.com/MarvellCareers |
| micron-technology | 403 | Workday `micron.wd1/External`: 600 (capped), 142 SG | **VERIFIED** | https://micron.wd1.myworkdayjobs.com/External |
| ncs-group | 403 | NCS hires through Singtel's SuccessFactors site. Search `q=NCS`, newest first: 25 NCS SG postings + 8 nav links. The SmartRecruiters `NCS` board is empty | **VERIFIED** (generic_html, see decision 3) | https://groupcareers.singtel.com/go/Engineering-NCS/4705410/ |
| nomura | 403 | SuccessFactors at careers.nomura.com, filtered to Singapore: 30 SG postings + 4 region links | **VERIFIED** (generic_html) | https://careers.nomura.com/Nomura/search/?q=&locationsearch=Singapore |
| paypal | 403 | Workday `paypal.wd1/jobs`: 278 postings, 17 SG | **VERIFIED** | https://paypal.wd1.myworkdayjobs.com/jobs |
| propertyguru | 403 | Workday `propertyguru.wd105/PropertyGuru`: 26 postings, 2 SG | **VERIFIED** | https://propertyguru.wd105.myworkdayjobs.com/PropertyGuru |
| qualcomm | 403 | Moved to Eightfold (careers.qualcomm.com). The old Workday tenant `qualcomm.wd5/External` returns 422 | UNVERIFIABLE: Eightfold | https://careers.qualcomm.com/ |
| revolut | 403 | In-house careers system. Revolut says it uses no third-party platforms. Greenhouse, Lever and Ashby all return 404 | UNVERIFIABLE: blocked, in-house | https://www.revolut.com/careers/ |
| sap | 403 | jobs.sap.com is SAP SuccessFactors on the blocked host. No other feed | UNVERIFIABLE: blocked | https://jobs.sap.com/ |
| tcs | 403 | tcs.com/careers/singapore is on the blocked host. No public ATS feed found | UNVERIFIABLE: blocked | https://www.tcs.com/careers/singapore |
| tsmc | 403 | careers.tsmc.com (Avature) SearchJobs also returns 403. There is a legacy tsmc.taleo.net, but no adapter for it | UNVERIFIABLE: blocked | https://careers.tsmc.com/en_US/careers/SearchJobs |
| wells-fargo | 403 | Workday `wf.wd1/WellsFargoJobs`: 600 (capped), 1 SG | **VERIFIED** | https://wf.wd1.myworkdayjobs.com/WellsFargoJobs |

## Priority for pasting (Singapore relevance)

OCBC (363 SG), Micron (142), GlobalFoundries (117), Infosys (116), Visa (51), Broadcom (31), Nomura (30),
NCS (25), Lam (25), NetEase (23), Marvell (21), PayPal (17), GoTo (12), then the rest. UOB (310 SG) is worth
the most of all, but only once decision 1 is made.
