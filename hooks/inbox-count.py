"""
SessionStart hook — pending-suggestion counter for the approval-gate inbox.

Loom's approval gate is "the assistant proposes; you approve." Proposals are
parked as unchecked checklist items in an inbox file (SUGGESTIONS.md by default)
instead of being applied silently. This hook counts the pending items at the
start of a session and prints a one-line reminder so they don't rot unseen.

Counts lines that begin with an unchecked checkbox (`- [ ]` or `[ ]`). If the
count is 0 it stays silent. If the file is missing or unreadable it exits 0
quietly (a SessionStart hook must never crash the session).
"""
import os
import sys

# ============================================================================
# CONFIG — adapt to your own layout.
# ----------------------------------------------------------------------------
# Inbox file holding pending proposals, relative to this hook's directory.
# Default: ~/.claude/SUGGESTIONS.md  (hooks live in ~/.claude/hooks/).
# Point this at whatever file you use to park assistant proposals for approval.
INBOX_REL = os.path.join("..", "SUGGESTIONS.md")
# ============================================================================


def main():
    inbox = os.path.join(os.path.dirname(__file__), INBOX_REL)
    try:
        with open(inbox, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        sys.exit(0)

    n = 0
    for ln in lines:
        stripped = ln.lstrip()
        if stripped.startswith("- [ ]") or stripped.startswith("[ ]"):
            n += 1

    if n > 0:
        sys.stdout.write(
            f"[inbox] {n} pending suggestion(s) awaiting your approval. "
            f"(Assistant: at the end of this session's first reply, tell the "
            f'user "{n} suggestion(s) are queued in the inbox — want to review '
            f'them?" before moving on. This is Loom\'s approval gate: propose, '
            f"then wait for approval.)\n"
        )
    sys.exit(0)


main()
