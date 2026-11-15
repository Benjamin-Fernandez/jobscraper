"""L5 availability: ordinary Singapore wordings whose tail is not frame vocabulary / function word. The model quotes
'Singapore' (what the real model does for plain 'in Singapore' wordings) and answers the right value."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
sys.path.insert(0, "tests")
src = open("docs/reviews/Q-121-closure-probes/p12.py", encoding="utf-8").read()
head = src.split('for mode in ("I", "R"):')[0]
ns = {}
exec(compile(head, "p12head", "exec"), ns)
Y, N = "Yes", "No"
ns["W"] = [
    ("Are you eligible to work in Singapore effective immediately?", Y),
    ("Will you be able to work in Singapore by 1 March?", Y),
    ("Are you able to work in Singapore starting next month?", Y),
    ("Are you able to work in Singapore upon hire?", Y),
    ("Are you legally authorised to work in Singapore on the date of joining?", Y),
    ("Are you authorised to work in Singapore beginning January?", Y),
    ("Do you have the right to work in Singapore throughout the contract period?", Y),
    ("Are you legally permitted to work in Singapore at all times?", Y),
    ("Are you authorised to work in Singapore as a full-time employee?", Y),
    ("Are you eligible to work in Singapore as an intern?", Y),
    ("Are you eligible to work in Singapore for the duration of the internship?", Y),
    ("Are you authorised to work in Singapore for the duration of this role?", Y),
    ("Are you authorised to work in Singapore throughout the internship (May to August)?", Y),
    ("Do you have the right to work in Singapore full time?", Y),
    ("Are you currently legally entitled to work in Singapore, including overtime?", Y),
    ("Do you have the right to work in Singapore, including any required security clearance?", Y),
    ("Do you have the right to work in Singapore without a visa or permit?", Y),
    ("Are you authorised to work in Singapore ahead of the start date?", Y),
    ("Are you authorised to work in Singapore regardless of your nationality?", Y),
    ("Are you authorised to work in Singapore currently or by the start date?", Y),
    ("Are you authorised to work in Singapore, and can you provide documents on request?", Y),
    ("Are you authorised to work in Singapore (Yes/No)?", Y),
    ("Do you have the right to work in Singapore? Please answer honestly.", Y),
    ("Are you authorised to work in Singapore for any employer, including ours?", Y),
    ("Do you have a valid right to work in Singapore for the whole of 2027?", Y),
    ("Do you require sponsorship to work in Singapore, either now or later?", N),
    ("Do you require sponsorship to work in Singapore once your studies end?", N),
    ("Do you require visa sponsorship to work in Singapore after graduation?", N),
    ("Will you require a work pass to work in Singapore after your internship?", N),
    ("Do you require sponsorship to work in Singapore beyond your current permit?", N),
]
for mode in ("I", "R"):
    a, e, w, rows = ns["run_all"](mode)
    print(f"== L5 availability mode {mode}: right {a} / empty {e} / wrong {w} of {len(ns['W'])}; place calls {sum(r[2] for r in rows)}")
    for tag, calls, pc, label, s in rows:
        if tag != "ok":
            print(f"   {tag:5} calls={calls} place={pc} | {label} -> {s}")
