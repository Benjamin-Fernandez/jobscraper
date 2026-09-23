"""Who the candidate is, derived from their resume.

The resume is the source of truth for skills and for the job titles worth looking
out for. It is parsed only when the file's hash changes, and the result is merged
with hand-written overrides the parser never overwrites.
"""
