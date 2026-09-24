"""Excel and HTML surfaces.

The application tracker is APPEND-ONLY. Columns left of the divider belong to the
program; columns right of it belong to you and are never touched once written.
"""
from __future__ import annotations

import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .models import Candidate
from .store_v1 import Store

PROGRAM_COLS = [
    ("job_id", 12), ("Found", 11), ("Run", 6), ("Company", 22), ("Tier", 6),
    ("Category", 14), ("Role", 52), ("Location", 20), ("Apply", 10),
    ("Score", 8), ("Verdict", 11), ("Why", 46), ("Posted", 11), ("Source", 14),
]
USER_COLS = [
    ("Status", 12), ("Date Applied", 13), ("Resume Version", 15),
    ("Referral", 14), ("Notes", 34), ("Outcome", 14),
]
N_PROGRAM = len(PROGRAM_COLS)
STATUSES = "To Apply,Applied,OA,Interview,Offer,Rejected,Skipped,Closed"

HEAD_FILL = PatternFill("solid", fgColor="1F2A37")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=10)
USER_HEAD_FILL = PatternFill("solid", fgColor="0B5A3E")
LINK_FONT = Font(color="1155CC", underline="single")
TIER_FILL = {
    "T1": PatternFill("solid", fgColor="FFF3CD"),
    "T2": PatternFill("solid", fgColor="E8F0FE"),
}


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# application tracker
# --------------------------------------------------------------------------

def _new_tracker() -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Applications"
    ws.append([h for h, _ in PROGRAM_COLS] + [h for h, _ in USER_COLS])
    for idx, (_name, width) in enumerate(PROGRAM_COLS + USER_COLS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
        cell = ws.cell(row=1, column=idx)
        cell.font = HEAD_FONT
        cell.fill = USER_HEAD_FILL if idx > N_PROGRAM else HEAD_FILL
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "D2"
    ws.column_dimensions["A"].hidden = True
    ws.row_dimensions[1].height = 22
    return wb


def _read_existing(path: Path) -> tuple[Optional[Workbook], set[str]]:
    if not path.exists():
        return None, set()
    try:
        wb = load_workbook(path)
    except Exception:
        return None, set()
    ws = wb["Applications"] if "Applications" in wb.sheetnames else wb.active
    seen = set()
    for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
        if row and row[0]:
            seen.add(str(row[0]))
    return wb, seen


def _rotate(folder: Path, keep: int) -> None:
    files = sorted(folder.glob("application_tracker-*.xlsx"))
    if len(files) > keep:
        for f in files[:-keep]:
            try:
                f.unlink()
            except Exception:
                pass


def write_application_tracker(path: Path, cands: list[Candidate], run_no: int,
                              store: Store) -> int:
    """Append new matches. Returns the number of rows added."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backups = path.parent / "backups"
    backups.mkdir(exist_ok=True)

    wb, seen = _read_existing(path)
    if wb is None:
        wb = _new_tracker()
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        try:
            shutil.copy2(path, backups / f"application_tracker-{stamp}.xlsx")
        except Exception:
            pass
        _rotate(backups, keep=5)

    ws = wb["Applications"] if "Applications" in wb.sheetnames else wb.active

    fresh = [c for c in cands
             if c.job_id not in seen and not store.already_exported(c.job_id)]
    order = {"T1": 0, "T2": 1, "T3": 2, "T4": 3, "Gov": 4}
    fresh.sort(key=lambda c: (order.get(c.company.tier, 9), -c.score.total))

    for c in fresh:
        verdict = c.verdict.verdict if c.verdict else "rule-only"
        ws.append([
            c.job_id, today(), run_no, c.company.name, c.company.tier,
            c.company.category, c.raw.title, c.raw.location or "(unstated)",
            "Open", round(c.score.total, 1), verdict, c.exportable_reason,
            c.raw.posted_at or "", c.company.provider or "",
            "To Apply", "", "", "", "", "",
        ])
        r = ws.max_row
        for col in (7, 9):                      # Role and Apply both clickable
            cell = ws.cell(row=r, column=col)
            if c.raw.url:
                cell.hyperlink = c.raw.url
                cell.font = LINK_FONT
        ws.cell(row=r, column=9).alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=12).alignment = Alignment(wrap_text=True,
                                                        vertical="top")
        fill = TIER_FILL.get(c.company.tier)
        if fill:
            ws.cell(row=r, column=5).fill = fill
        store.mark_exported(c.job_id, run_no)

    last = max(ws.max_row, 2)
    ws.auto_filter.ref = f"A1:{get_column_letter(N_PROGRAM + len(USER_COLS))}{last}"

    dv = DataValidation(type="list", formula1=f'"{STATUSES}"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"O2:O{last}")

    score_col = f"J2:J{last}"
    ws.conditional_formatting.add(score_col, CellIsRule(
        operator="greaterThanOrEqual", formula=["70"],
        fill=PatternFill("solid", fgColor="C6EFCE")))
    ws.conditional_formatting.add(score_col, CellIsRule(
        operator="between", formula=["50", "69.9"],
        fill=PatternFill("solid", fgColor="FFEB9C")))

    tmp = path.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(path)
    return len(fresh)


# --------------------------------------------------------------------------
# applied state -> tracker
# --------------------------------------------------------------------------

STATUS_COL = N_PROGRAM + 1          # O
DATE_COL = N_PROGRAM + 2            # P
APPLIED_SHEET = "Applied"
# Statuses that mean "further along than applied". Never walked backwards.
BEYOND = {"oa", "interview", "offer", "rejected"}


def sync_applied(path: Path, store: Store) -> int:
    """Push the applied ticks from the database into the tracker workbook.

    Only two of your columns are ever touched, and only in the safe direction:

      Status        blank / "To Apply"  ->  "Applied"      (on tick)
                    "Applied"           ->  "To Apply"     (on un-tick)
      Date Applied  blank               ->  the applied date
                    the applied date    ->  blank          (on un-tick)

    A status you moved on yourself - OA, Interview, Offer, Rejected - is left
    exactly as it is, and so is a date you typed yourself. Every other user
    column (Resume Version, Referral, Notes, Outcome) is never read or written.
    Returns the number of rows changed.
    """
    if not path.exists():
        return 0
    try:
        wb = load_workbook(path)
    except Exception:
        return 0
    ws = wb["Applications"] if "Applications" in wb.sheetnames else wb.active
    applied = store.applied_map()
    changed = 0

    for row in ws.iter_rows(min_row=2, max_col=DATE_COL):
        job_id = row[0].value
        if not job_id:
            continue
        rec = applied.get(str(job_id))
        status_cell = ws.cell(row=row[0].row, column=STATUS_COL)
        date_cell = ws.cell(row=row[0].row, column=DATE_COL)
        current = str(status_cell.value or "").strip()

        if rec:
            if current.lower() in BEYOND:
                continue                    # you are past "applied" - leave it
            if current.lower() != "applied":
                status_cell.value = "Applied"
                changed += 1
            if not str(date_cell.value or "").strip():
                date_cell.value = rec["applied_at"]
                date_cell.alignment = Alignment(horizontal="center")
                changed += 1
        else:
            if current.lower() == "applied":
                status_cell.value = "To Apply"
                date_cell.value = None
                changed += 1

    _write_applied_sheet(wb, store)

    tmp = path.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(path)
    return changed


def _write_applied_sheet(wb: Workbook, store: Store) -> None:
    """A clean chronological log of what you have applied to. Regenerated."""
    if APPLIED_SHEET in wb.sheetnames:
        del wb[APPLIED_SHEET]
    ws = wb.create_sheet(APPLIED_SHEET)
    ws.append(["Date Applied", "Company", "Tier", "Role", "Score",
               "Application link"])
    for r in store.applied_rows():
        ws.append([r["applied_at"] or "", r["company"] or "", r["tier"] or "",
                   r["role"] or "", round(r["score"], 1) if r["score"] else "",
                   r["url"] or ""])
        cell = ws.cell(row=ws.max_row, column=6)
        if r["url"]:
            cell.hyperlink = r["url"]
            cell.font = LINK_FONT
            cell.value = "Open posting"
        role_cell = ws.cell(row=ws.max_row, column=4)
        if r["url"]:
            role_cell.hyperlink = r["url"]
            role_cell.font = LINK_FONT
    for i, w in enumerate([13, 24, 6, 52, 8, 18], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
        ws.cell(row=1, column=i).font = HEAD_FONT
        ws.cell(row=1, column=i).fill = USER_HEAD_FILL
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 20


# --------------------------------------------------------------------------
# run tracker
# --------------------------------------------------------------------------

def write_run_tracker(path: Path, store: Store) -> None:
    wb = Workbook()
    runs = wb.active
    runs.title = "Runs"
    runs.append(["Run", "Cycle", "From", "To", "Started", "Finished", "Status",
                 "Companies", "OK", "Failed", "Skipped", "Postings", "New",
                 "Matched", "LLM calls", "In tokens", "Out tokens"])
    for r in store.all_runs():
        s = json.loads(r["stats_json"] or "{}")
        runs.append([
            r["run_no"], r["cycle_id"], r["batch_from"], r["batch_to"],
            r["started_at"], r["finished_at"], r["status"],
            s.get("companies", 0), s.get("ok", 0), s.get("failed", 0),
            s.get("skipped", 0), s.get("postings", 0), s.get("new", 0),
            s.get("matched", 0), s.get("calls", 0),
            s.get("input_tokens", 0), s.get("output_tokens", 0),
        ])

    cov = wb.create_sheet("Coverage")
    cov.append(["Run", "Company", "Tier", "Status", "Provider", "Postings",
                "New", "Matched", "HTTP", "Error class", "Error", "Checked at",
                "Careers page"])
    for r in store.coverage_rows():
        cov.append([
            r["run_no"], r["name"], r["tier"], r["status"], r["provider"] or "",
            r["postings_found"], r["new_count"], r["matched_count"],
            r["http_status"] or "", r["error_class"] or "", r["error"] or "",
            r["checked_at"], r["careers_url"] or "",
        ])

    for ws, widths in (
            (runs, [6, 7, 7, 7, 20, 20, 12, 11, 6, 8, 9, 10, 7, 9, 10, 11, 11]),
            (cov, [6, 24, 6, 10, 15, 10, 7, 9, 7, 12, 48, 20, 46])):
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
            c = ws.cell(row=1, column=i)
            c.font = HEAD_FONT
            c.fill = HEAD_FILL
        ws.freeze_panes = "A2"

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(path)


def write_needs_review(path: Path, store: Store) -> int:
    wb = Workbook()
    ws = wb.active
    ws.title = "Needs review"
    ws.append(["#", "Company", "Tier", "Careers page", "Provider", "Failures",
               "Last error class", "Last error", "Quarantined at",
               "Probation due run", "Paste correct feed URL here"])
    rows = 0
    for c in store.quarantined():
        ws.append([c.ordinal, c.name, c.tier, c.careers_url, c.provider or "",
                   c.consecutive_failures, c.last_error_class or "",
                   c.last_error or "", c.quarantined_at or "",
                   c.probation_due_run or "", ""])
        rows += 1
    for i, w in enumerate([5, 24, 6, 46, 15, 9, 14, 52, 20, 10, 40], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
        ws.cell(row=1, column=i).font = HEAD_FONT
        ws.cell(row=1, column=i).fill = HEAD_FILL
    ws.freeze_panes = "A2"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(path)
    return rows


# --------------------------------------------------------------------------
# cards - the shape the page renders
# --------------------------------------------------------------------------

def _card(job_id, title, company, tier, location, url, score, verdict, why):
    return {"job_id": str(job_id), "title": title or "", "company": company or "",
            "tier": tier or "", "location": location or "", "url": url or "",
            "score": float(score or 0), "verdict": verdict or "rule-only",
            "why": why or ""}


def cards_from_candidates(cands: list[Candidate]) -> list[dict]:
    return [_card(c.job_id, c.raw.title, c.company.name, c.company.tier,
                  c.raw.location, c.raw.url, c.score.total,
                  c.verdict.verdict if c.verdict else "rule-only",
                  c.exportable_reason)
            for c in cands]


def cards_from_tracker(path: Path) -> list[dict]:
    """Rebuild every exported match from the tracker workbook.

    The tracker is the one place that already holds all of it - role, link,
    score, verdict and the reason - so the page can be regenerated at any time
    without re-fetching anything.
    """
    if not path.exists():
        return []
    try:
        wb = load_workbook(path)
    except Exception:
        return []
    ws = wb["Applications"] if "Applications" in wb.sheetnames else wb.active
    out = []
    for row in ws.iter_rows(min_row=2, max_col=N_PROGRAM):
        job_id = row[0].value
        if not job_id:
            continue
        url = row[6].hyperlink.target if row[6].hyperlink else ""
        out.append(_card(job_id, row[6].value, row[3].value, row[4].value,
                         row[7].value, url, row[9].value, row[10].value,
                         row[11].value))
    return out


# --------------------------------------------------------------------------
# HTML view
# --------------------------------------------------------------------------

HTML_CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1a1a1a;--mut:#6b7280;--line:#e5e7eb;
--acc:#1155cc;--ok:#0a7a3d;--okbg:#e4f6ea;--warnbg:#fff4d6;--warnink:#7a5a00}
*{box-sizing:border-box}
body{margin:0;padding:0;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:28px 18px 60px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:8px}
.count{font-size:13px;color:var(--mut);margin-bottom:20px}
.count b{color:var(--ok)}
.banner{background:var(--warnbg);color:var(--warnink);border-radius:9px;
padding:11px 14px;font-size:13.5px;margin-bottom:18px;line-height:1.5}
.banner code{background:rgba(0,0,0,.08);padding:1px 6px;border-radius:4px;
font-size:12.5px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin-bottom:10px;display:flex;gap:14px;align-items:flex-start;
border-left:3px solid transparent;transition:opacity .15s,border-color .15s}
.card:hover{border-color:#c7ccd4}
.card.done{border-left-color:var(--ok);opacity:.62}
.card.done .role a{text-decoration:line-through}
.score{flex:0 0 52px;height:52px;border-radius:8px;display:flex;align-items:center;
justify-content:center;font-weight:700;font-size:17px;background:#eef2f7}
.s-hi{background:#d8f0dd;color:#0a5c2a}.s-mid{background:#fdf0c9;color:#7a5a00}
.body{flex:1;min-width:0}
.role{font-size:16px;font-weight:650;margin:0 0 3px}
.role a{color:var(--acc);text-decoration:none}
.role a:hover{text-decoration:underline}
.meta{color:var(--mut);font-size:13px;margin-bottom:6px}
.why{font-size:13.5px;color:#333}
.tag{display:inline-block;font-size:11px;font-weight:600;padding:2px 7px;
border-radius:999px;background:#eef2f7;color:#41506b;margin-right:6px}
.t1{background:#fff0c4;color:#7a5a00}.t2{background:#e2ecff;color:#1c4fa1}
.act{flex:0 0 132px;align-self:center;display:flex;flex-direction:column;gap:8px}
.act a.apply{display:block;text-align:center;padding:8px 14px;border-radius:7px;
background:var(--acc);color:#fff;text-decoration:none;font-size:13px;
font-weight:600}
.chk{display:flex;align-items:center;justify-content:center;gap:7px;
border:1px solid var(--line);border-radius:7px;padding:7px 10px;font-size:13px;
font-weight:600;color:var(--mut);cursor:pointer;background:var(--card);
user-select:none}
.chk:hover{border-color:#b9c0ca}
.chk input{width:15px;height:15px;margin:0;cursor:pointer;accent-color:var(--ok)}
.card.done .chk{background:var(--okbg);border-color:#9bd6b1;color:var(--ok)}
.chk.saving{opacity:.5}
.chk.error{border-color:#d9534f;color:#d9534f}
.stamp{font-size:11px;color:var(--mut);text-align:center;min-height:13px}
.empty{padding:40px;text-align:center;color:var(--mut)}
@media(max-width:560px){.card{flex-wrap:wrap}.act{flex:1 1 100%;flex-direction:row}
.act a.apply{flex:1}.chk{flex:1}}
@media(prefers-color-scheme:dark){
:root{--bg:#15171a;--card:#1d2024;--ink:#e8e8e6;--mut:#9aa3ae;--line:#2b2f35;
--acc:#7aa7ff;--ok:#5fd18c;--okbg:#1b2b22;--warnbg:#3a3116;--warnink:#e8cf8a}
.score{background:#262b31}.why{color:#c5cbd3}.tag{background:#262b31;color:#a9b6c9}
.act a.apply{color:#10131a}
.card.done .chk{background:#1b2b22;border-color:#2f5b42}}
"""

# Talks to the local viewer (`jobscraper view`). Opened straight off disk there is
# no server to talk to, so the ticks are disabled rather than silently lost.
HTML_JS = r"""
(function () {
  var live = location.protocol === 'http:' || location.protocol === 'https:';
  var boxes = Array.prototype.slice.call(
      document.querySelectorAll('.chk input[type=checkbox]'));

  function card(el) { return el.closest('.card'); }
  function stampOf(el) { return card(el).querySelector('.stamp'); }

  function paint(el, on, when) {
    card(el).classList.toggle('done', !!on);
    stampOf(el).textContent = on && when ? 'applied ' + when : '';
  }

  function total() {
    var n = boxes.filter(function (b) { return b.checked; }).length;
    var c = document.getElementById('count');
    if (c) c.innerHTML = '<b>' + n + '</b> of ' + boxes.length +
                         ' marked applied';
  }

  if (!live) {
    var b = document.getElementById('banner');
    if (b) b.hidden = false;
    boxes.forEach(function (el) { el.disabled = true; });
    total();
    return;
  }

  fetch('/api/state').then(function (r) { return r.json(); })
    .then(function (state) {
      boxes.forEach(function (el) {
        var rec = state[el.dataset.job];
        if (rec && rec.applied) {
          el.checked = true;
          paint(el, true, rec.applied_at);
        }
      });
      total();
    }).catch(function () { total(); });

  boxes.forEach(function (el) {
    el.addEventListener('change', function () {
      var wrap = el.parentNode;
      wrap.classList.add('saving');
      wrap.classList.remove('error');
      paint(el, el.checked, '');
      fetch('/api/applied', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: el.dataset.job, applied: el.checked,
          role: el.dataset.role, company: el.dataset.company,
          url: el.dataset.url
        })
      }).then(function (r) {
        if (!r.ok) { throw new Error(r.status); }
        return r.json();
      }).then(function (res) {
        wrap.classList.remove('saving');
        paint(el, el.checked, res.applied_at);
        total();
      }).catch(function () {
        wrap.classList.remove('saving');
        wrap.classList.add('error');
        el.checked = !el.checked;      // roll the tick back, nothing was saved
        paint(el, el.checked, '');
        total();
      });
    });
  });
})();
"""


def _cls(score: float) -> str:
    return "s-hi" if score >= 70 else ("s-mid" if score >= 50 else "")


def write_html_view(path: Path, items, run_no: int, batch_label: str,
                    heading: str = "") -> None:
    """Render the match page. `items` is Candidates or cards from the tracker."""
    cards_in = (items if (items and isinstance(items[0], dict))
                else cards_from_candidates(items))
    order = {"T1": 0, "T2": 1, "T3": 2, "T4": 3, "Gov": 4}
    rows = sorted(cards_in, key=lambda c: (order.get(c["tier"], 9), -c["score"]))
    e = html.escape
    cards = []
    for c in rows:
        tier_cls = {"T1": "t1", "T2": "t2"}.get(c["tier"], "")
        verdict = c["verdict"]
        url = e(c["url"])
        cards.append(f"""
  <div class="card" data-card="{e(c["job_id"])}">
    <div class="score {_cls(c["score"])}">{c["score"]:.0f}</div>
    <div class="body">
      <p class="role"><a href="{url}" target="_blank" rel="noopener">{e(c["title"])}</a></p>
      <div class="meta">
        <span class="tag {tier_cls}">{e(c["tier"])}</span>
        <strong>{e(c["company"])}</strong> &middot;
        {e(c["location"] or 'location unstated')} &middot;
        <span class="tag">{e(verdict)}</span>
      </div>
      <div class="why">{e(c["why"])}</div>
    </div>
    <div class="act">
      <a class="apply" href="{url}" target="_blank" rel="noopener">Apply</a>
      <label class="chk">
        <input type="checkbox" data-job="{e(c["job_id"])}"
               data-role="{e(c["title"])}"
               data-company="{e(c["company"])}"
               data-url="{url}">
        <span>Applied</span>
      </label>
      <div class="stamp"></div>
    </div>
  </div>""")

    body = "\n".join(cards) if cards else (
        '<div class="empty">No new matches in this batch.</div>')
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JobScraper run {run_no}</title><style>{HTML_CSS}</style></head>
<body><div class="wrap">
<h1>{e(heading) if heading else f"New matches &mdash; run {run_no}"}</h1>
<div class="sub">{e(batch_label)} &middot; {len(rows)} match(es) &middot; generated {stamp}</div>
<div class="count" id="count"></div>
<div class="banner" id="banner" hidden>
  This page was opened straight off disk, so the <strong>Applied</strong> ticks are
  switched off &mdash; nothing here can reach your tracker. Start the viewer with
  <code>.\\run.ps1 view</code> and tick them there instead.
</div>
{body}
</div><script>{HTML_JS}</script></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
