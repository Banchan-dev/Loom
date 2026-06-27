#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# PreToolUse 훅 (Bash/PowerShell) — 무거운 명령을 foreground로 돌리려 하면 '차단'.
# Loom 비전 강제: "오래 걸리는 건 백그라운드로"를 보여주기만 말고 행동으로 강제한다.
#   훅은 입력(보게)뿐 아니라 '도구 차단'은 가능 → 이걸로 행동까지 강제.
# 보수적: claude 재귀 위임/배치·마이닝 러너처럼 '결과 바로 안 봐도 되는 무거운 것'만 차단.
#   codex exec 는 제외("잠깐 걸려요" 예고 후 결과를 바로 종합하는 관례).
import sys
import json
import re

# ============================================================================
# CONFIG — tool/command names. Adapt these to your toolchain.
# ----------------------------------------------------------------------------
# Substring that marks a "cross-check" command which should NOT be blocked
# (it runs briefly and its result is consumed right away). If your cross-check
# tool isn't `codex exec`, change this.
CODEX_EXEC_MARKER = "codex exec"
# Command prefixes that only hold a string (don't actually launch work) -> allow.
ALLOW_PREFIXES = ("git ", "echo ", "cat ", "grep ", "rg ", "ls ", "#")
# ============================================================================

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

inp = data.get("tool_input", {}) or {}
cmd = str(inp.get("command", ""))
bg = bool(inp.get("run_in_background", False))

# git·echo·grep 등 'claude를 실행하지 않고 문자열로만 품는' 명령은 통과(오탐 방지)
_stripped = cmd.lstrip()
if _stripped.startswith(ALLOW_PREFIXES) or CODEX_EXEC_MARKER in cmd:
    sys.exit(0)

# 무거운(=백그라운드로 돌렸어야 할) 명령 패턴
HEAVY = [
    r"\bclaude\s+(-p|exec)\b",   # claude 재귀 위임/배치 (마이닝·서브 분석 등)
    r"\brun_miner\b",            # 마이닝 러너
]

if not bg and any(re.search(p, cmd) for p in HEAVY):
    sys.stderr.write(
        "[Loom 강제 — 백그라운드] 이 명령은 오래 걸리는 무거운 작업이다. "
        "foreground로 돌리면 사용자가 그 시간 내내 기다리게 된다.\n"
        "→ run_in_background=true 로 다시 던지고, 사용자와는 즉시 다른 대화/작업을 이어가라. "
        "(결과는 끝나면 알림으로 온다)\n"
    )
    sys.exit(2)  # 도구 차단

sys.exit(0)
