"""The only step that costs anything: ask a cheap model to judge a posting.

Two halves. `vital_extract` reduces a job description to the few hundred
characters that actually decide the question - location, experience, the top of
the requirements - discarding culture copy and benefits boilerplate. Then one
batched call to the cheapest available model returns accept or reject.

What the model says is not the last word. Location and the experience ceiling are
re-checked in code afterwards, so no amount of model confidence can put a
non-Singapore or over-senior role on the shortlist.

See PRD sections 8.3[4] and 8.3[5].
"""
