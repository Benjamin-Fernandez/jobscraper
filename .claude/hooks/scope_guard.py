"""PreToolUse hook: blocks Edit/Write outside a role's write scope.

Scopes live in .claude/scopes.json (the single source of truth; keep it in sync
with instructions/04_team.md section 2).

- A named subagent (hook input has agent_type) may write only to its "allow"
  patterns minus its "deny" patterns.
- "protected" patterns are blocked for everyone, the main session included.
- The main session is unrestricted unless "enforce_main_session" is true, in
  which case it may write only to "main_session_allow".
- Fail-open on a missing or broken scopes.json or an unknown role, so a config
  slip never locks the project. Every decision is logged to
  .claude/hooks/logs/scope_guard.log (gitignored) for auditing.

Pattern syntax: "dir/" or "dir/**" = everything under dir; an exact path; or a
glob with * or ? (fnmatch). Paths are relative to the project root, with / as
the separator. A path inside an agent worktree (.claude/worktrees/<name>/...)
is checked as if it were in the main checkout, so parallel lanes keep their
scopes.
Exit code 2 blocks the call and sends stderr back to the agent.
"""
import fnmatch
import json
import os
import re
import sys
from datetime import datetime, timezone

CASE_INSENSITIVE = os.name == "nt"
WORKTREE_PREFIX = re.compile(r"^\.claude/worktrees/[^/]+/", re.I)


def norm(p: str) -> str:
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lower() if CASE_INSENSITIVE else p


def rel_path(path: str, root: str) -> str:
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    except ValueError:  # different drive on Windows
        return norm(path)
    return norm(rel)


def matches(rel: str, pattern: str) -> bool:
    pat = norm(pattern)
    if pat.endswith("/**"):
        pat = pat[:-2]
    is_glob = any(c in pat for c in "*?[")
    # fnmatch's * also matches "/"; "/**/" may match zero folders.
    fpat = pat.replace("/**/", "/*")
    if pat.endswith("/"):
        return fnmatch.fnmatchcase(rel, fpat + "*") if is_glob else rel.startswith(pat)
    if is_glob:
        return fnmatch.fnmatchcase(rel, fpat)
    return rel == pat or rel.startswith(pat + "/")


def log(root: str, entry: dict) -> None:
    try:
        log_dir = os.path.join(root, ".claude", "hooks", "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "scope_guard.log"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def block(msg: str) -> int:
    sys.stderr.write(msg)
    return 2


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    tool_input = data.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not target:
        return 0
    rel = WORKTREE_PREFIX.sub("", rel_path(target, root))
    agent = data.get("agent_type") or data.get("agent_name") or data.get("subagent_type")

    try:
        with open(os.path.join(root, ".claude", "scopes.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as exc:
        log(root, {"ts": datetime.now(timezone.utc).isoformat(), "error": f"scopes.json: {exc}"})
        return 0  # fail-open

    entry = {"ts": datetime.now(timezone.utc).isoformat(), "agent": agent,
             "tool": data.get("tool_name"), "path": rel}

    for pat in cfg.get("protected", []):
        if matches(rel, pat):
            log(root, {**entry, "result": "blocked:protected"})
            return block(f"scope_guard: '{rel}' is protected; no agent may write it "
                         "(.claude/scopes.json 'protected'). Ask the owner.")

    roles = cfg.get("roles", {})
    if not agent:
        if cfg.get("enforce_main_session") and not any(
                matches(rel, p) for p in cfg.get("main_session_allow", [])):
            log(root, {**entry, "result": "blocked:main"})
            return block(f"scope_guard: the Coordinator doesn't write '{rel}'. "
                         "Delegate it to the owning role (instructions/04_team.md).")
        log(root, {**entry, "result": "allowed:main"})
        return 0

    if agent not in roles:
        log(root, {**entry, "result": "allowed:unknown-role"})
        return 0  # fail-open for roles not listed (e.g. built-in agents)

    scope = roles[agent]
    allowed = any(matches(rel, p) for p in scope.get("allow", []))
    denied = any(matches(rel, p) for p in scope.get("deny", []))
    if allowed and not denied:
        log(root, {**entry, "result": "allowed"})
        return 0

    log(root, {**entry, "result": "blocked"})
    return block(
        f"scope_guard: '{agent}' may not write '{rel}'. Allowed: {scope.get('allow', [])}"
        f"{' except ' + str(scope.get('deny')) if scope.get('deny') else ''}. "
        f"Log a request in comms/outbox/{agent}.md for the owning role instead "
        "(instructions/04_team.md section 3)."
    )


if __name__ == "__main__":
    sys.exit(main())
