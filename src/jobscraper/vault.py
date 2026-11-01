"""Passwords for ATS accounts and the IMAP mailbox (apply_design.md §10.1, §10.3).

Foundation module (NF-04): the stage (`apply/`), the orchestrator, the CLI and
the web layer all reach Windows Credential Manager through here, never through
`keyring` directly, so there is one place that handles a secret.

Rules (NF-02, F-35):
  - Only passwords are stored, one entry per `jobscraper:<ats>:<host>` target
    and username (spike S-1d: the blob limit is ~2.5 KB; entries show in
    Credential Manager as `LegacyGeneric:target=jobscraper:...`).
  - A secret travels inside `contracts.Secret` (it never prints) and is never
    logged, not even its length. Errors name the service, never the value.
  - `keyring` is imported lazily: modules that import this one (the CLI, web)
    keep working on a machine without it; only an actual vault call fails, with
    a `VaultError` that says what to install. Tests swap the backend with
    `keyring.set_keyring(...)`, which this module honours on every call.
  - The Edge CSV (§10.3) is the one place a password touches the disk. It lives
    in `data/` (gitignored by `data/*.csv`), is overwritten with zeros before it
    is deleted, and anything older than an hour is removed by
    `purge_stale_exports`.
"""
from __future__ import annotations

import csv
import logging
import os
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Union

from .apply.contracts import PasswordRules, Secret

log = logging.getLogger(__name__)

SERVICE_PREFIX = "jobscraper"
IMAP_SERVICE = "jobscraper:imap:{host}"          # username = the IMAP login (§11.5)

EXPORT_GLOB = "edge_passwords_*.csv"
EXPORT_HEADER = ("name", "url", "username", "password", "note")
EXPORT_NOTE = "JobScraper"
EXPORT_MAX_AGE_S = 3600                          # §10.3: removed after 1 hour
_STAMP_FMT = "%Y%m%dT%H%M%SZ"
_STORE_TIME_FMT = "%Y-%m-%dT%H:%M:%S"            # store.TIME_FMT (UTC, naive text)


class VaultError(RuntimeError):
    """A vault call failed. The message names the service, never the secret."""


def service_for(ats: str, host: str) -> str:
    """The Credential Manager target for an ATS tenant: `jobscraper:<ats>:<host>`.

    Same shape as `contracts.Tenant.vault_service`.
    """
    return f"{SERVICE_PREFIX}:{ats.strip().lower()}:{host.strip().lower()}"


def imap_service(host: str) -> str:
    """`IMAP_SERVICE` for a host; two Gmail accounts share it and differ by username."""
    return IMAP_SERVICE.format(host=host.strip().lower())


def _kr():
    try:
        import keyring
    except ImportError as exc:                     # pragma: no cover - env without keyring
        raise VaultError("the `keyring` package is not installed "
                         "(pip install -r requirements.txt)") from exc
    return keyring


# ---------------------------------------------------------------- get / put / delete

def get(service: str, username: str) -> Optional[Secret]:
    """The stored password, or None when there is no entry."""
    try:
        value = _kr().get_password(service, username)
    except VaultError:
        raise
    except Exception as exc:
        raise VaultError(f"could not read the vault entry for {service}: "
                         f"{type(exc).__name__}") from None
    return None if value is None else Secret(value)


def put(service: str, username: str, secret: Secret) -> None:
    """Store a password, then read it back and compare (§10.2 step 2).

    A mismatch or any backend error raises `VaultError`: the caller must not go
    on to submit a sign-up whose password was not kept.
    """
    if not isinstance(secret, Secret):
        raise TypeError("vault.put takes a contracts.Secret")
    if not secret.reveal():
        raise VaultError(f"refusing to store an empty password for {service}")
    kr = _kr()
    try:
        kr.set_password(service, username, secret.reveal())
        back = kr.get_password(service, username)
    except Exception as exc:
        raise VaultError(f"could not write the vault entry for {service}: "
                         f"{type(exc).__name__}") from None
    if back != secret.reveal():
        raise VaultError(f"the vault entry for {service} did not read back as written")


def delete(service: str, username: str) -> None:
    """Remove an entry. A missing entry is not an error."""
    kr = _kr()
    try:
        from keyring.errors import PasswordDeleteError
    except ImportError:                            # pragma: no cover
        PasswordDeleteError = ()                   # type: ignore[assignment]
    try:
        kr.delete_password(service, username)
    except PasswordDeleteError:
        return
    except Exception as exc:
        raise VaultError(f"could not delete the vault entry for {service}: "
                         f"{type(exc).__name__}") from None


# ---------------------------------------------------------------- generator

def generate(rules: PasswordRules) -> Secret:
    """A random password that meets `rules` (§10.1).

    Length = `rules.length` clamped to [min_length, max_length] (and to at least
    one character per required class); one character from each required class,
    the rest from the union of the allowed classes, shuffled with SystemRandom.
    """
    rng = secrets.SystemRandom()
    classes: list[str] = []
    if rules.need_upper:
        classes.append(string.ascii_uppercase)
    if rules.need_lower:
        classes.append(string.ascii_lowercase)
    if rules.need_digit:
        classes.append(string.digits)
    if rules.need_symbol and rules.symbols:
        classes.append(rules.symbols)
    # The union always has letters and digits, even when no class is required.
    pool = string.ascii_letters + string.digits + (rules.symbols or "")
    lo = max(1, rules.min_length)
    hi = max(lo, rules.max_length)
    length = max(lo, min(rules.length, hi), len(classes))
    chars = [rng.choice(c) for c in classes]
    chars += [rng.choice(pool) for _ in range(length - len(chars))]
    rng.shuffle(chars)
    return Secret("".join(chars))


# ---------------------------------------------------------------- Edge CSV (§10.3)

def _row_get(row: Any, *names: str) -> str:
    for n in names:
        v = row.get(n) if isinstance(row, Mapping) else getattr(row, n, None)
        if v:
            return str(v)
    return ""


def export_edge_csv(rows: Iterable[Any], out_dir: Union[str, os.PathLike]) -> Path:
    """Write `edge_passwords_<UTC stamp>.csv` in `out_dir` for Edge's import (§10.3).

    `rows` are `ats_accounts` rows (mappings or objects with `ats`,
    `tenant_host`, `email` and optionally `vault_service`); the caller picks the
    ones with `exported_to_edge_at IS NULL`. Each password comes from the vault;
    a row without a stored password (e.g. `exists_no_password`) is skipped.
    Header `name,url,username,password,note`; name = `<ATS> <tenant host>`,
    url = `https://<tenant host>/`, username = email, note = `JobScraper`.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"edge_passwords_{datetime.now(timezone.utc).strftime(_STAMP_FMT)}.csv"
    n = 1
    while path.exists():                           # two exports in one second
        path = out / f"edge_passwords_{datetime.now(timezone.utc).strftime(_STAMP_FMT)}_{n}.csv"
        n += 1
    body: list[tuple[str, ...]] = []
    for row in rows:
        ats = _row_get(row, "ats")
        host = _row_get(row, "tenant_host", "host").lower()
        email = _row_get(row, "email")
        if not (ats and host and email):
            continue
        service = _row_get(row, "vault_service") or service_for(ats, host)
        secret = get(service, email)
        if secret is None:
            continue
        label = ats[:1].upper() + ats[1:]
        body.append((f"{label} {host}", f"https://{host}/", email, secret.reveal(), EXPORT_NOTE))
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(EXPORT_HEADER)
        w.writerows(body)
    log.info("Edge password export written: %s (%d accounts)", path.name, len(body))
    return path


def delete_export(path: Union[str, os.PathLike]) -> None:
    """Overwrite the export with zeros, flush it to disk, then unlink it."""
    p = Path(path)
    try:
        size = p.stat().st_size
    except FileNotFoundError:
        return
    with open(p, "r+b") as fh:
        fh.write(b"\0" * size)
        fh.flush()
        os.fsync(fh.fileno())
    p.unlink()


def _epoch(now: Union[datetime, str, float, int, None]) -> float:
    if now is None:
        return datetime.now(timezone.utc).timestamp()
    if isinstance(now, (int, float)):
        return float(now)
    if isinstance(now, str):
        now = datetime.strptime(now, _STORE_TIME_FMT).replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.timestamp()


def purge_stale_exports(data_dir: Union[str, os.PathLike],
                        now: Union[datetime, str, float, int, None] = None) -> int:
    """Delete (zero-overwrite) every export in `data_dir` older than 1 hour.

    `now`: a datetime (naive = UTC), a `store.utcnow()` string, or epoch seconds.
    Age is the file's modification time. Returns the number removed.
    """
    d = Path(data_dir)
    if not d.is_dir():
        return 0
    cutoff = _epoch(now) - EXPORT_MAX_AGE_S
    removed = 0
    for p in d.glob(EXPORT_GLOB):
        try:
            if p.stat().st_mtime < cutoff:
                delete_export(p)
                removed += 1
        except OSError as exc:
            log.warning("could not remove stale export %s: %s", p.name, type(exc).__name__)
    return removed
