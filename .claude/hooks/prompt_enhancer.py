"""UserPromptSubmit hook: reminds the Coordinator to enhance the prompt first.

Stdout from a UserPromptSubmit hook is added to the model's context. Very short
prompts (approvals like "yes", "ok go") get no reminder, to save tokens.
See instructions/03_methods.md section 1.
"""
import json
import sys

REMINDER = (
    "[prompt-enhancer] Before acting, apply instructions/03_methods.md section 1: "
    "enhance this prompt (Goal, Scope & owner, Context, Constraints, Deliverable, "
    "Acceptance criteria, Ambiguities). Show a compact 'Enhanced prompt' block (<= 7 lines), "
    "or a one-line restatement if trivial, then act on the enhanced version. "
    "Delegations use the template in section 2 with a budget. Spawn agents only if needed "
    "(04_team.md section 4). Run the loop in 05_workflow.md section 1; keep status, queue "
    "and handover current. Nothing is built before its design is READY TO BUILD."
)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    prompt = ""
    try:
        prompt = (json.load(sys.stdin) or {}).get("prompt", "") or ""
    except Exception:
        pass
    if len(prompt.split()) > 3:
        print(REMINDER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
