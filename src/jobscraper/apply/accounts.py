"""Which email signs in or signs up on an ATS tenant (apply_design §10.5, D-70).

Pure: no I/O, no vault, no store. `apply_flow` hands in the tenant's account
rows and a `has_password` probe (the vault lookup), so the rule is testable
without Credential Manager and the flow stays the one place that writes.

Rules, in order (emails compared lower-case; backup "" = none):
  1. the first of (primary, backup) with a stored password whose row is not
     `signin_failed` / `exists_no_password` -> sign in with it;
  2. a `signin_failed` row and rule 1 found nothing -> LOGIN_FAILED (a second
     automatic sign-in could lock the account; the owner fixes it with
     `accounts add`, which stores the password and resets the row);
  3. the primary is `exists_no_password` -> sign up with the backup when it is
     set and has no row, else LOGIN_FAILED;
  4. otherwise sign up with the primary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .contracts import AccountStatus, ApplyFailure, ReasonCode

SIGN_IN = "sign_in"
SIGN_UP = "sign_up"

SIGNIN_FAILED_DETAIL = ("Sign-in failed on this site before; JobScraper won't retry, "
                        "to avoid locking the account.")
NO_PASSWORD_DETAIL = ("An account exists for your email but JobScraper has no password for it. "
                      "Add a backup email to your profile, or add the password with "
                      "`accounts add`.")
BOTH_NO_PASSWORD_DETAIL = ("Accounts exist for both your emails, but JobScraper has no "
                           "password for them.")

_BLOCKED = frozenset({AccountStatus.SIGNIN_FAILED.value, AccountStatus.EXISTS_NO_PASSWORD.value})


@dataclass(frozen=True)
class Identity:
    email: str
    action: str            # "sign_in" | "sign_up"


def _lower(rows: Mapping[str, str]) -> dict[str, str]:
    return {str(k).strip().lower(): str(v) for k, v in rows.items()}


def choose_identity(primary: str, backup: str, rows: Mapping[str, str],
                    has_password: Callable[[str], bool]) -> Identity:
    """The identity for this attempt (apply_design §10.5 rules 1-4).

    `rows`: {email: AccountStatus value} for this tenant (any case);
    `has_password(email)`: a vault entry exists for that email (called with the
    address as the profile spells it). Raises ApplyFailure(LOGIN_FAILED) for
    rules 2 and 3 with a detail that names no address.
    """
    primary = (primary or "").strip()
    backup = (backup or "").strip()
    if backup.lower() == primary.lower():
        backup = ""
    status = _lower(rows)
    emails = [e for e in (primary, backup) if e]
    for e in emails:                                                       # rule 1
        if status.get(e.lower()) not in _BLOCKED and has_password(e):
            return Identity(e, SIGN_IN)
    if any(status.get(e.lower()) == AccountStatus.SIGNIN_FAILED.value for e in emails):
        raise ApplyFailure(ReasonCode.LOGIN_FAILED, SIGNIN_FAILED_DETAIL)   # rule 2
    if status.get(primary.lower()) == AccountStatus.EXISTS_NO_PASSWORD.value:  # rule 3
        if backup and backup.lower() not in status:
            return Identity(backup, SIGN_UP)
        raise ApplyFailure(ReasonCode.LOGIN_FAILED,
                           BOTH_NO_PASSWORD_DETAIL if backup else NO_PASSWORD_DETAIL)
    return Identity(primary, SIGN_UP)                                      # rule 4
