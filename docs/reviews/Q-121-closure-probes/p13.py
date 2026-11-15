"""Q7 batch 2: wordings that are not in the pure form. Reuses p12's machinery (everything before its final loop)."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
sys.path.insert(0, "tests")
src = open("docs/reviews/Q-121-closure-probes/p12.py", encoding="utf-8").read()
head = src.split('for mode in ("I", "R"):')[0]
ns = {}
exec(compile(head, "p12head", "exec"), ns)
Y, N = "Yes", "No"
ns["W"] = [
    ("Are you allowed to work in Singapore on a full-time basis?", Y),
    ("Are you legally able to work in Singapore for any employer?", Y),
    ("Are you eligible to work in Singapore for an indefinite period?", Y),
    ("Do you hold the right to work in Singapore without a work pass?", Y),
    ("Do you require a visa or work permit to work in Singapore?", N),
    ("Are you a Singapore citizen/PR?", Y),
    ("Are you currently residing in Singapore?", Y),
    ("Are you eligible to be employed in Singapore?", Y),
    ("Are you able to provide proof of your right to work in Singapore?", Y),
    ("Are you a citizen, permanent resident or work pass holder in Singapore?", Y),
    ("Do you have a valid work permit for Singapore?", N),
    ("Will you require Employment Pass sponsorship from us?", N),
    ("Do you currently have permission to work in Singapore for any employer?", Y),
    ("Is Singapore your country of citizenship?", Y),
    ("Do you have the legal right to be employed in Singapore without needing a work pass?", Y),
    ("Are you legally allowed to work in Singapore without any restrictions or sponsorship?", Y),
    ("Please confirm you have the legal right to work in Singapore", Y),
    ("I am legally authorised to work in Singapore", Y),
    ("I am a Singapore citizen or Permanent Resident", Y),
    ("I do not require visa sponsorship to work in Singapore", Y),
    ("I will require sponsorship to work in Singapore", N),
    ("Are you a Singapore citizen, Permanent Resident or Foreigner?", Y),
    ("Are you currently a Singapore citizen or Permanent Resident of Singapore?", Y),
    ("Do you have the right to work in Singapore (citizen, PR or valid pass)?", Y),
    ("Do you already hold work authorisation in Singapore?", Y),
    ("Are you authorised to work in Singapore for employers other than your current one?", Y),
    ("Are you authorised to work in Singapore and willing to relocate?", Y),
    ("Do you have an existing right to work in Singapore that does not require sponsorship?", Y),
    ("Are you eligible to work in Singapore without needing an employer-sponsored pass?", Y),
    ("Have you been granted permission to work in Singapore?", Y),
    ("Are you Singapore-based and authorised to work here?", Y),
    ("Are you currently legally entitled to be employed in Singapore, on a full-time permanent basis?", Y),
    ("Do you have the legal right to work in Singapore on a permanent basis?", Y),
    ("Work authorization status in Singapore", Y),
    ("Are you authorised to work in your country of residence?", Y),
    ("Do you currently reside in Singapore and have the right to work?", Y),
    ("Are you legally able to work in Singapore and the US?", N),
    ("Are you authorised to work in the US?", N),
    ("Are you authorised to work in the United States?", N),
    ("Will you require sponsorship to work in the US?", Y),
    ("Are you authorised to work in Malaysia?", N),
]
for mode in ("I", "R"):
    a, e, w, rows = ns["run_all"](mode)
    print(f"== batch2 mode {mode}: answered-right {a} / empty {e} / wrong {w} of {len(ns['W'])}; model calls {sum(r[1] for r in rows)}, place calls {sum(r[2] for r in rows)}")
    for tag, calls, pc, label, s in rows:
        if tag != "ok":
            print(f"   {tag:5} calls={calls} place={pc} | {label} -> {s}")
