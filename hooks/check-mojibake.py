"""
PostToolUse hook — after Edit/Write/MultiEdit, scan .md files for U+FFFD
replacement characters (a common sign of corrupted/mojibake text, e.g.
broken non-ASCII encoding). On detection, warn on stderr + exit 2 so the
agent fixes it. Useful for any codebase with non-ASCII content.
"""
import sys
import json
import os

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

fp = data.get("tool_input", {}).get("file_path", "")
if not fp or not fp.endswith(".md") or not os.path.isfile(fp):
    sys.exit(0)

try:
    with open(fp, "rb") as f:
        content = f.read()
except Exception as e:
    # permission/lock/race: don't crash the hook, but leave a visible trace so
    # a failing check isn't silently swallowed.
    sys.stderr.write(f"[check-mojibake] Could not read {fp}: {e}\n")
    sys.exit(0)

if bytes([0xEF, 0xBF, 0xBD]) in content:
    sys.stderr.write(
        f"Corrupted text (U+FFFD replacement character) found: {fp}\n"
        "Likely a mojibake/encoding error. Fix to proper UTF-8 text now.\n"
    )
    sys.exit(2)
