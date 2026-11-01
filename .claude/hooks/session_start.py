"""SessionStart hook: puts the handover note and open outbox items in context.

This makes "read the instructions before acting" deterministic: every new,
resumed, cleared or compacted session starts with where the last one stopped.
Stdout from a SessionStart hook is added to the model's context.
"""
import glob
import os
import re
import sys

MAX_HANDOVER_LINES = 60
MAX_OPEN_ITEMS = 15


def main() -> int:
    # Windows consoles default to cp1252, which can't print characters such as "→".
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    out = ["[session-start] Read CLAUDE.md and the handover note before acting. "
           "Then run the Coordinator loop (instructions/05_workflow.md section 1)."]

    handover = os.path.join(root, "instructions", "handover.md")
    if os.path.exists(handover):
        with open(handover, encoding="utf-8") as f:
            lines = f.read().splitlines()
        if len(lines) > MAX_HANDOVER_LINES:
            out.append(f"WARNING: handover.md has {len(lines)} lines (limit 40). Rewrite it "
                       "and move the history to docs/planning/session_log.md.")
        # CLAUDE.md imports the handover; repeat it only if the import is missing.
        claude_md = os.path.join(root, "CLAUDE.md")
        imported = os.path.exists(claude_md) and "@instructions/handover.md" in open(
            claude_md, encoding="utf-8").read()
        if not imported:
            out.append("--- instructions/handover.md ---")
            out.extend(lines[:MAX_HANDOVER_LINES])

    open_items = []
    for path in sorted(glob.glob(os.path.join(root, "comms", "outbox", "*.md"))):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)  # skip the template comment
        for block in re.split(r"\n(?=### )", text):
            if block.startswith("### ") and re.search(r"STATUS:\s*open", block, re.I):
                open_items.append(f"{os.path.basename(path)}: {block.splitlines()[0][4:]}")
    if open_items:
        out.append(f"Open outbox items ({len(open_items)}):")
        out.extend(f"- {i}" for i in open_items[:MAX_OPEN_ITEMS])
        if len(open_items) > MAX_OPEN_ITEMS:
            out.append(f"- ... and {len(open_items) - MAX_OPEN_ITEMS} more")

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
