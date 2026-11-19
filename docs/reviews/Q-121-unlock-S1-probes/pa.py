"""Q2 (a)+(b): 70 adversarial labels the status predicate might wrongly claim, or that pass the plain test while asking
about another entity / time. Owner = the sample profile (Singapore citizen, not PR, no pass, job in Singapore).
Cells: [model right, faithful calls] [model WRONG, faithful calls] [model WRONG, confirmer repeats the model (2nd wrong call)]
Marks: ! = a value differing from the right one is written; ? = right is None (nothing settles it) and a value is written
UNASSUMED; F = right is None and the source cites the owner's nationality / residency (a fact used for another question);
* = written and marked assumed."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S1-probes")
from h2 import *  # noqa

# (label, right, group)
A = [
    ("Are you a permanent resident physician?", None, "a"),
    ("Are you a citizen service officer?", None, "a"),
    ("Do you hold a PR qualification?", None, "a"),
    ("Are you a national account manager?", None, "a"),
    ("Are you a foreigner-friendly landlord?", None, "a"),
    ("Are you a citizen scientist?", None, "a"),
    ("Are you a resident doctor?", None, "a"),
    ("Are you a PR professional?", None, "a"),
    ("Are you a PR manager?", None, "a"),
    ("Are you a national champion?", None, "a"),
    ("Are you a citizen of the world?", None, "a"),
    ("Are you a resident assistant?", None, "a"),
    ("Do you have a citizen journalism portfolio?", None, "a"),
    ("Do you hold a PR degree?", None, "a"),
    ("Do you have PR experience?", None, "a"),
    ("Do you have experience with national accounts?", None, "a"),
    ("Do you have citizenship education experience?", None, "a"),
    ("Are you a foreigner in your own team?", None, "a"),
    ("Are you a Singapore national scholar?", None, "a"),
    ("Do you hold a work pass for the gym?", None, "a"),
    ("Do you hold a PR certificate in public relations?", None, "a"),
    ("Are you a resident of Atlantis?", None, "a"),
    ("Are you a permanent resident of the hall?", None, "a"),
    ("Are you a national of another country?", None, "a"),
    ("Are you a citizen of another country as well?", None, "a"),
    # (b) another entity / time but pass the plain test or G3
    ("Is the applicant a Singapore citizen?", None, "b"),
    ("Is he a Singapore citizen?", None, "b"),
    ("Is your sponsor a Singapore citizen?", None, "b"),
    ("Is your company a Singapore PR?", None, "b"),
    ("Are you or your spouse a Singapore citizen?", None, "b"),
    ("Are your parents Singapore PRs?", None, "b"),
    ("Is your employer a Singapore citizen?", None, "b"),
    ("Were you a Singapore citizen at birth?", "Yes", "b"),
    ("Have you been a Singapore citizen since 2020?", "Yes", "b"),
    ("Will you be a Singapore PR by the start date?", "No", "b"),
    ("Were you a Singapore PR before becoming a citizen?", None, "b"),
    ("Have you ever been a Singapore PR?", None, "b"),
    ("Are you a Singapore citizen as of 1 January 2020?", "Yes", "b"),
    ("Did you hold a Singapore work pass in 2022?", None, "b"),
    ("Do you currently hold a Singapore citizen?", None, "b"),
    ("Are you a Singapore citizen and willing to relocate?", None, "b"),
    ("Are you a Singapore citizen who is willing to work shifts?", None, "b"),
    ("Are you a Singapore citizen or can you obtain a work pass?", None, "b"),
    ("Are you a Singapore citizen? Do you speak Mandarin?", None, "b"),
    ("Are you a Singapore citizen and a university student?", None, "b"),
    ("Are you a Singapore citizen studying overseas?", None, "b"),
    ("Are you both a Singapore citizen and a US citizen?", "No", "b"),
    ("Are you a Singapore citizen, PR, or foreigner?", None, "b"),
    ("Are you a Singapore citizen with a valid passport?", None, "b"),
    ("Are you a Singapore citizen aged 21 or above?", None, "b"),
    ("Are you a Singapore citizen or PR with 2 years of experience?", None, "b"),
    # no country
    ("Are you a citizen or permanent resident?", "Yes", "c"),
    ("Are you a PR?", "No", "c"),
    ("Are you a foreigner?", "No", "c"),
    ("Are you a non-citizen?", "No", "c"),
    ("Citizen or PR?", "Yes", "c"),
    ("Do you hold citizenship or permanent residency?", "Yes", "c"),
    ("Do you hold an Employment Pass?", "No", "c"),
    ("Do you have a work pass?", "No", "c"),
    ("Are you a citizen, PR or foreign national?", None, "c"),
    ("Are you a citizen or a foreigner?", None, "c"),
    ("I am a citizen", "Yes", "c"),
    ("Are you a citizen by birth?", "Yes", "c"),
    ("Have you been a permanent resident since 2020?", "No", "c"),
    ("Are you a citizen? If no, please state your visa type", None, "c"),
]


def opp(v):
    return "No" if v == "Yes" else "Yes"


if __name__ == "__main__":
    bad = []
    for label, right, grp in A:
        for ft in ("RADIO", "CHECKBOX"):
            sq = AL.status_question(mk(label, ft, YN if ft == "RADIO" else ()), "SG")
            sqs = f"{sorted(sq.kinds)}/{sq.country or '??'}/{'plain' if sq.plain else 'G3'}" if sq else "-"
            cells = []
            for (m, conf) in (("right", "faithful"), ("wrong", "faithful"), ("wrong", "follow")):
                if ft == "RADIO":
                    mv = (right or "Yes") if m == "right" else opp(right or "Yes")
                else:
                    mv = {"Yes": "true", "No": "false"}[(right or "Yes") if m == "right" else opp(right or "Yes")]
                r = run(label, mv, "work_right", conf, right, ft, required=(ft == "RADIO"))
                s = cell(r)
                if ft == "CHECKBOX":
                    s = {"TICK*": "T*", "TICK": "T", "-": "-"}.get(s, s)
                mark = ""
                w = r["written"]
                if ft == "RADIO" and right is not None and w in ("Yes", "No") and w != right:
                    mark = "!"
                if right is None and w not in ("-", "STOP") and not r["assumed"]:
                    mark += "?"
                if right is None and w not in ("-", "STOP") and sourced_from_fact(r):
                    mark += "F"
                cells.append(f"{s}{mark}")
                if "!" in mark or "?" in mark or "F" in mark:
                    bad.append((label, ft, m, conf, r["written"], r["src"], r["assumed"]))
            print(f"{grp} {ft[:5]:5} {label[:66]:66} r={right!s:4} sq={sqs:26} | " + "  ".join(cells))
    print("\nMARKED:")
    for b in bad:
        print(b)
