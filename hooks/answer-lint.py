"""
Stop hook — answer-format linter (mechanically enforces answer style rules).

The most reliable lever for output quality in Claude Code is the Stop hook's
exit 2 (reject -> regenerate). Output quality cannot be 100% enforced, and the
semantic layer (judging jargon, picking what matters) cannot be caught by a
machine, so this hook only checks things that are deterministically certain —
length and (optionally) banned wording/tone.

Design:
- If an answer obeys the rules, it just passes (zero extra checks). Only a
  violation triggers a reject -> rewrite.
- Within one user turn a violating answer may be rejected up to MAX_BLOCKS
  times (forcing a rewrite). After that, violations pass = infinite-loop guard,
  and the final judgment stays with the human.
- Code blocks / inline code / quoted text / blockquotes are excluded from the
  check (avoids false positives).
"""
import sys
import json
import re
import os

# ============================================================================
# CONFIG — EDIT THESE TO MAKE THE LINTER YOURS (or disable rules you don't want)
# ----------------------------------------------------------------------------
# The two rules below are EXAMPLES. They are NOT universal. Tune them, replace
# them, or switch them off:
#   * length cap  -> set CHECK_LENGTH = False, or change MAX_BODY_CHARS
#   * tone/wording -> set CHECK_TONE   = True and fill in the TONE_PATTERN regex
# Everything still works with both rules off (the hook just always passes).
# ============================================================================

# --- Rule 1: length cap -----------------------------------------------------
CHECK_LENGTH = False  # opt-in: the 1-line/3-point shape is a personal taste, not universal
# Max body chars (code/quotes excluded). Over this = "too long" -> reject.
# This value is a personal preference; raise/lower it freely.
MAX_BODY_CHARS = 1500

# How many times a violating answer may be rejected within one user turn.
# After this, violations pass (infinite-loop guard). Not style-specific.
MAX_BLOCKS = 2

# --- Rule 2: tone / wording (OPT-IN, OFF BY DEFAULT) ------------------------
# Tone/wording rules are language- and taste-dependent, so this is disabled by
# default. To use it, set CHECK_TONE = True and put the wording you want to ban
# into TONE_PATTERN. The example below is empty (matches nothing) on purpose —
# replace it with your own forbidden patterns, e.g.:
#   TONE_PATTERN = re.compile(r"\b(kindly|please note|as an AI)\b", re.I)
CHECK_TONE = False
TONE_PATTERN = re.compile(
    r"(?!x)x"  # placeholder: matches nothing. Put your banned wording here.
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
    """Scan backwards for the real user prompt (excluding tool_result) = the
    start of the current turn."""
    for i in range(len(lines) - 1, -1, -1):
        msg = lines[i].get("message", lines[i])
        role = msg.get("role") or lines[i].get("type")
        if role != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return i
        if isinstance(content, list):
            if any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            ):
                continue
            if any(
                isinstance(b, dict) and b.get("type") == "text" for b in content
            ):
                return i
    return 0


def assistant_texts_after(lines, start):
    """Return assistant message texts after `start` in order (non-empty only)."""
    out = []
    for rec in lines[start:]:
        msg = rec.get("message", rec)
        role = msg.get("role") or rec.get("type")
        if role != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            if content.strip():
                out.append(content)
        elif isinstance(content, list):
            texts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            joined = "\n".join(t for t in texts if t)
            if joined.strip():
                out.append(joined)
    return out


def strip_noncontent(text):
    """Remove parts excluded from the check — code/quotes are outside the rules."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)   # fenced code blocks
    text = re.sub(r"`[^`]*`", "", text)                       # inline code
    text = re.sub(r'"[^"]*"', "", text)                       # ASCII double quotes
    text = re.sub(r"'[^']*'", "", text)                       # ASCII single quotes
    text = re.sub(r"[“”][^“”]*[“”]", "", text)  # smart double quotes
    text = re.sub(r"[‘’][^‘’]*[‘’]", "", text)  # smart single quotes
    text = re.sub(r"[「『][^」』]*[」』]", "", text)  # CJK quote brackets
    # drop blockquote (>) lines
    text = "\n".join(
        l for l in text.split("\n") if not l.lstrip().startswith(">")
    )
    return text


def check_violations(raw):
    """Return the list of rule violations for one answer (empty list = pass)."""
    body = strip_noncontent(raw)
    body_len = len(body.replace("\n", "").replace(" ", ""))
    violations = []
    if CHECK_LENGTH and body_len > MAX_BODY_CHARS:
        violations.append(
            f"- Too long: body is {body_len} chars (code/quotes excluded) > "
            f"limit {MAX_BODY_CHARS}. Cut to a 1-line conclusion + at most 3 "
            "key points. Move details into a document."
        )
    if CHECK_TONE:
        m = TONE_PATTERN.search(body)
        if m:
            violations.append(
                f"- Banned wording found: '{m.group(0)}'. Rewrite to match the "
                "configured tone rule."
            )
    return violations


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tp = data.get("transcript_path")
    if not tp or not os.path.isfile(tp):
        sys.exit(0)

    lines = load_transcript(tp)
    if not lines:
        sys.exit(0)

    boundary = find_boundary(lines)
    answers = assistant_texts_after(lines, boundary)
    if not answers:
        sys.exit(0)

    # If the current (last) answer obeys the rules, pass immediately — no extra checks.
    cur_viol = check_violations(answers[-1])
    if not cur_viol:
        sys.exit(0)

    # Count violating answers in this turn (current included). Over MAX_BLOCKS = safety-valve pass.
    viol_count = sum(1 for a in answers if check_violations(a))
    if viol_count > MAX_BLOCKS:
        sys.exit(0)

    sys.stderr.write(
        f"[answer linter] Answer-format rule violation "
        f"({viol_count}/{MAX_BLOCKS} this turn — fix it to pass):\n"
        + "\n".join(cur_viol)
        + "\n-> Fix and answer again. If this is genuinely justified (long "
        "quote, structurally unavoidable), leave a one-line reason and stop "
        "again to pass.\n"
    )
    sys.exit(2)


main()
