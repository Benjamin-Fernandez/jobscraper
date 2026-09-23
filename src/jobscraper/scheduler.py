"""Who is due to be scraped, and when.

A company is due when it has never been scraped, or was last scraped more than
`cycle_days` ago. Each run takes the `batch_size` most-neglected due companies.

This replaces v1's global cursor. A cursor answers "how far through the list are
we"; it cannot answer "has *this company* been checked in the past two weeks",
which is the actual question - and the one that makes looping back to the first
company stop being a special case.

`last_scraped_at` is stamped on attempt, not success: a company that reliably
returns 403 must not monopolise every batch.

See PRD section 8.3[0].
"""
