# Install

## Requirements
- [Claude Code](https://claude.com/claude-code)
- `python3` on your PATH (the hooks are Python)
- A bash-capable shell (the hooks use `shell: bash`). Built on Windows (Git Bash); macOS/Linux should work, the worktree-cleanup hook was Windows-specific and is not included.

## Steps
1. **Clone** this repo.
2. **Copy** these into your Claude config directory (`~/.claude/`):
   - `hooks/`  → `~/.claude/hooks/`
   - `skills/` → `~/.claude/skills/`
   - `output-styles/` → `~/.claude/output-styles/`
3. **Register the hooks**: merge the `hooks` block from `settings.example.json` into your `~/.claude/settings.json`.
4. **Fill in your personal layer** (see below). Without it, the engine runs but has nothing about *you* to act on.

## The hooks — read each before enabling

Hooks run code automatically on matching events. Read them before turning them on — this is opt-in by design.

| Hook | When | What it does |
|------|------|--------------|
| `answer-lint.py` | Stop | Blocks your final answer if it breaks your length/tone rules and forces **one** rewrite. ⚠️ Defaults encode the author's taste (Korean, terse, no honorifics) — edit the rules inside to your own. Second pass always passes (no infinite loop). |
| `lint-router.py` | UserPromptSubmit | Injects situational rules / knowledge cards by keyword match. |
| `heavy-bg-gate.py` | PreToolUse (Bash) | Nudges heavy commands to run in the background. |
| `check-mojibake.py` | PostToolUse (edits) | Flags broken text encoding after a file edit. |
| `codex-gate.py` | Stop — **OPTIONAL** | Nudges you to cross-verify code edits with an external model. ⚠️ **Requires the `codex` CLI, and it is a nudge, not a hard gate** — a second stop passes through. Omitted from `settings.example.json`; add it only if you use codex. |

## Personal layer (you fill this in)

The engine is intentionally empty of personal content. The three pieces below are what make it useful. Start with the always-on rules — that alone changes how every answer comes out.

### Walkthrough: always-on rules in 3 steps

This is the highest-value piece. It injects *your* rules on every prompt, so the assistant starts from your defaults instead of generic ones.

**1. Create a rules file** at `~/.claude/MY_RULES.md`.

**2. Put a few plain rules in it.** Keep it short — these get injected every turn, so bloat costs you. Example content:

```markdown
# My rules

- Answer in English. Conclusion first, then only the details that matter.
- Keep it short. No filler, no restating my question back to me.
- When a request is ambiguous, ask before assuming.
- Show working code or test output before saying something is "done."
```

**3. Inject it every turn** with a `UserPromptSubmit` hook. Add this to the `hooks` block in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "cat ~/.claude/MY_RULES.md" }
        ]
      }
    ]
  }
}
```

Whatever the hook prints to stdout is prepended to your prompt as context. Restart Claude Code, and from now on every turn carries your rules. (This is exactly how the included `lint-router.py` hook works — it just adds keyword-based card matching on top.)

### The other two pieces

- **Knowledge cards** — markdown notes under your own `cards/` dir, auto-loaded by `lint-router` when your prompt contains a card's trigger word. Use these for per-topic conventions you don't want injected on *every* turn.
- **Personal knowledge / memory** — facts about you and your projects that the assistant can pull in when relevant.

⚠️ **Keep all personal data in gitignored files.** The included `.gitignore` already excludes the common ones (`*.local.md`, `cards/`, `memory/`, rules files, tokens). Never commit anything about yourself if you plan to share your fork.

## A note on language

`loom/LOOM.md` is the **author's personal design canon, in Korean, left untranslated** — it's the design record behind the engine, not something you need to read to install or use Loom. Some defaults (e.g. the `answer-lint.py` rules) assume Korean conventions like 존댓말/반말 (formal vs. casual speech) that **don't apply to English** — replace them with your own preferences when you edit the hook.
