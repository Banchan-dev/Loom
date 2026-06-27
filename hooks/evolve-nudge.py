"""
Stop hook — conditional self-improvement nudge (NON-BLOCKING, always exit 0).

When this user turn shows a sign that something worth recording happened, this
hook prints one stderr line reminding the assistant to log it to the approval
inbox (SUGGESTIONS.md) as a single factual line — to be approved later, never
applied silently. Loom does not self-modify; it captures candidate improvements
for the human to approve.

It fires when ANY of these is detected in the turn:
  1. a file was edited (Edit/Write/MultiEdit/NotebookEdit)
  2. the user expressed explicit discomfort / correction
  3. the user stated a new standing preference
  4. the user described a manual / repetitive chore worth automating

If none match, it stays completely silent. Fires at most once per turn and
never interrupts the conversation (the Stop is always allowed through).

The transcript-parsing helpers are borrowed verbatim from codex-gate.py.
"""
import json
import os
import sys


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


def user_text(lines):
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


# ============================================================================
# CONFIG — signal vocabulary. These are EXAMPLES (English); edit to your own.
# ----------------------------------------------------------------------------
# Kept deliberately conservative — match only clear phrasing to avoid firing on
# every turn. Matching is case-insensitive (see main()).
#  (2) explicit discomfort / correction
DISCOMFORT = ("that's not", "thats not", "not what i", "wrong", "no, ",
              "redo", "do it again", "don't do that", "dont do that",
              "stop doing", "i don't like", "i dont like", "that's annoying")
#  (3) new standing preference
PREFERENCE = ("from now on", "always ", "every time", "i prefer", "i'd rather",
              "as a rule", "by default", "going forward", "make it a habit")
#  (4) manual / repetitive chore
MANUAL = ("every single time", "manually", "by hand", "one by one",
          "over and over", "i keep having to", "tedious", "this is repetitive")
# ============================================================================


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # Second entry stays silent (avoid duplicate nudges).
    if data.get("stop_hook_active"):
        sys.exit(0)

    tp = data.get("transcript_path")
    if not tp or not os.path.isfile(tp):
        sys.exit(0)

    lines = load_transcript(tp)
    if not lines:
        sys.exit(0)

    recent = lines[find_boundary(lines):]

    # (1) detect a file edit (Edit/Write/...)
    file_edit = False
    for rec in recent:
        msg = rec.get("message", rec)
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use" \
                    and b.get("name") in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                file_edit = True

    low = user_text(lines).lower()
    discomfort = any(s in low for s in DISCOMFORT)
    preference = any(s in low for s in PREFERENCE)
    manual = any(s in low for s in MANUAL)

    if file_edit or discomfort or preference or manual:
        sys.stderr.write(
            "[evolve] If this turn surfaced something worth keeping, confirm you "
            "logged a one-line factual note in the inbox (SUGGESTIONS.md) for the "
            "user to approve later. Propose, don't apply silently.\n"
        )

    sys.exit(0)


main()
