"""
Stop hook — cross-check code gate (OPT-IN NUDGE, not enforcement).

If a code file was edited in this user turn but there is no trace of an external
cross-check (a second model / CLI being run), this hook blocks the first stop
(exit 2) and asks for a cross-check. It is a one-time reminder, not hard
enforcement: the second stop (stop_hook_active) passes, so the gate nudges once
and leaves the final call to the human. The point is to surface a cross-check
rule from your config as a hook reminder instead of relying on a document.

Design decision: the second stop (stop_hook_active=true) is always allowed
through. The human is the supervisor — the gate only prevents a numbed-out
auto-stop by asking for at least one cross-check or an explicit skip reason.
"""
import sys
import json
import re
import os

# ============================================================================
# CONFIG — externalized so you can adapt this hook without editing logic.
# ----------------------------------------------------------------------------
# This gate looks for evidence that an EXTERNAL cross-checker (any second model
# or CLI) was run during the turn. The default below matches `codex exec ...`
# purely as an EXAMPLE — replace it with the command name of whatever tool you
# use for cross-checking. This is an opt-in nudge, not a mandate.
CROSS_CHECK_CMD_RE = re.compile(r"\bcodex\s+exec\b")

# Trigger words below are EXAMPLES (English). Edit them to your own vocabulary.
# ============================================================================

CODE_EXT = (
    ".py", ".cpp", ".h", ".hpp", ".c", ".cc", ".cs", ".js", ".ts", ".tsx",
    ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".swift", ".m",
    ".mm", ".sh", ".ps1", ".lua", ".sql",
)


def load_transcript(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
    except Exception:
        pass
    return out


def find_boundary(lines):
    """Scan backwards for the real user prompt (excluding tool_result)."""
    for i in range(len(lines) - 1, -1, -1):
        msg = lines[i].get("message", lines[i])
        role = msg.get("role") or lines[i].get("type")
        if role != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return i
        if isinstance(content, list):
            is_tool_result = any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )
            if is_tool_result:
                continue
            has_text = any(
                isinstance(b, dict) and b.get("type") == "text" for b in content
            )
            if has_text:
                return i
    return 0


def last_user_text(lines):
    """Return the joined text of the last real user prompt (for signal detection)."""
    i = find_boundary(lines)
    msg = lines[i].get("message", lines[i])
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


# Review-mode signals — if the user asks for a "review/final" pass, request one
# cross-check even when no code was edited. Two tiers to reduce over/under-firing:
#  - strong signals: intent is clear -> fire on their own
#  - weak signals: can appear in everyday text -> fire only alongside an
#    artifact/risk context word
# EXAMPLE signal words (English). Edit to your own vocabulary.
STRONG_SIGNALS = ("review this", "adversarial", "critique", "red team",
                  "tear apart", "cross-check", "double-check this")
WEAK_SIGNALS = ("final", "submit", "deploy", "release", "commit", "ship")
ARTIFACT_CTX = ("code", "doc", "report", "card", "hook", "script", "plan",
                "design", "pr")


def is_review_mode(text):
    low = text.lower()
    if any(s in low for s in STRONG_SIGNALS):
        return True
    if any(w in low for w in WEAK_SIGNALS) and any(a in low for a in ARTIFACT_CTX):
        return True
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # Second entry passes (infinite-loop guard + human supervisor).
    if data.get("stop_hook_active"):
        sys.exit(0)

    tp = data.get("transcript_path")
    if not tp or not os.path.isfile(tp):
        sys.exit(0)

    lines = load_transcript(tp)
    if not lines:
        sys.exit(0)

    recent = lines[find_boundary(lines):]

    code_edit = False
    cross_checked = False
    for rec in recent:
        msg = rec.get("message", rec)
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            name = b.get("name", "")
            inp = b.get("input", {}) or {}
            if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                fp = (inp.get("file_path") or inp.get("notebook_path") or "").lower()
                if fp.endswith(CODE_EXT):
                    code_edit = True
            elif name in ("Bash", "PowerShell"):
                cmd = inp.get("command", "") or ""
                if CROSS_CHECK_CMD_RE.search(cmd):
                    cross_checked = True

    # Review mode: a "review/final" signal requests one cross-check regardless
    # of whether code was edited.
    review_mode = is_review_mode(last_user_text(lines))
    if review_mode and not cross_checked:
        sys.stderr.write(
            "[review/final nudge] The user gave a review/final/submit signal but "
            "there is no trace of an external cross-check.\n"
            "Suggested: run a second model/CLI over the artifact with an "
            "adversarial-review request and synthesize the result, OR — if this "
            "was a false positive — leave a one-line reason and stop again (the "
            "second stop passes).\n"
        )
        sys.exit(2)

    if code_edit and not cross_checked:
        sys.stderr.write(
            "[code gate] A code file was edited this turn but there is no trace "
            "of an external cross-check.\n"
            "Suggested: run a second model/CLI with a change summary + review "
            "request and synthesize the result, OR — if this is genuinely "
            "trivial — leave a one-line skip reason and stop again (the second "
            "stop passes).\n"
        )
        sys.exit(2)

    sys.exit(0)


main()
