# Loom

**Teach it once. Everything you do with AI gets sharper.**
*It layers in your context, learns you over time, and sharpens everything you do.*

A blueprint for a **user-directed personalization layer** on top of [Claude Code](https://claude.com/claude-code).

Loom turns Claude Code into an assistant that gets more personalized **as you add rules and feedback** — it does not learn or rewrite itself on its own. You write behavior rules, personal knowledge, and context-specific "cards"; hooks then nudge the assistant toward your preferences and scan your prompt to pull the right notes back in. Every change is **user-approved** — nothing self-modifies silently (a deliberate guard against an AI quietly rewriting its own rules).

> **What "user-directed" means in practice:** the value comes from what *you* put in. Loom doesn't observe you and infer rules; it gives you slots to record rules/knowledge and the plumbing to surface them at the right moment.

> **This is a blueprint, not a finished product.**
> The *engine* ships here; the *contents* (who you are, your rules, your projects) are yours to fill in. A fresh clone is intentionally close to an empty shell — that is the design, not a bug. You fork it and grow your own.

## What it actually does (before / after)

Concrete, not abstract — here's what changes once you've filled in your layer:

- **Topic notes show up on their own.** You write a card about, say, *performance tuning* with the trigger word `performance`.
  - *Before:* you re-explain your conventions every time, or Claude forgets them.
  - *After:* your prompt contains "performance" → that card is auto-injected into context for that turn. (Keyword match — see the honest limit below.)
- **Answers come out the way you want.** You set a rule like "keep answers short, conclusion first."
  - *Before:* you keep asking Claude to be more concise.
  - *After:* a Stop hook checks the answer against your length/tone rule and nudges one rewrite if it runs long.
- **Your preferences ride along every turn.** Your always-on rules file is injected on each prompt, so the assistant starts from *your* defaults instead of generic ones.
- **Pick up exactly where you left off.** You keep one handoff note that records what you and the assistant were doing — current state, what's done, what's next — and the assistant keeps it current as you work.
  - *Before:* every new terminal session starts cold; you re-explain what you were in the middle of.
  - *After:* open Claude Code from any folder, any time, and the assistant reads the handoff note first — so you continue mid-thread instead of restarting from scratch.

The point: you state a preference **once**, and the engine keeps re-applying it — instead of you repeating yourself.

## What's inside

- **Behavior hooks** — e.g. an answer-format linter that nudges a response violating your length/tone rules toward a rewrite, plus a cross-verification gate.
  - ⚠️ *Honest limit:* these are **nudges, not hard guarantees.** A Stop hook can reject a response once and force a rewrite, but the second pass always goes through (to avoid infinite loops). Treat it as a strong reminder, not an absolute lock.
- **Context router** — injects the right rules per prompt, matched by keyword.
- **Knowledge cards** — markdown notes auto-loaded when your prompt matches their triggers. Ranking splits keywords into *anchors* (real topic words) vs *facets* (generic words like "bug/todo" that can't summon a card alone, only add points), weights by IDF, and — if your cards carry `domain/area/kind` frontmatter — narrows by area then discriminates by kind. When a prompt spans several areas with no kind cue, it adds a one-line *clarify* hint instead of guessing.
  - ⚠️ *Honest limit:* it's still **keyword-based**, so it can miss when your natural-language prompt avoids the trigger words entirely. The anchor/facet split and hierarchy cut over-firing and area-confusion, but recall is best-effort, not guaranteed (no embeddings/vectors — deliberately, to stay stdlib-only and instant).
- **Skills** — `planner` (adversarial feasibility check *before* you build), `interview` (pull your vision out through questioning), `humanizer` (strip AI-tells from writing).
  - **`loom`** (⚠️ *experimental — not validated end-to-end*) — first-run setup wizard (and re-config). After install, run `/loom`: with your consent it scans the chats and project folders you point it at for explicit instructions and interviews you, then drafts your personal layer (answer style, tone, rules) for your approval. Re-run `/loom` anytime to adjust. Treat it as a starting point, not a finished flow.
- **Output style** — readability/formatting defaults you can customize.

## Design principles

- **Drawer model** — five kinds of memory: always-on rules / personal knowledge / topic cards / engine spec / session handoff. Only the small "always-on" set is injected every turn; the rest is pulled in on demand.
- **Approval gate** — the assistant *proposes*; you *approve*. No silent self-editing.
- **Anti-bloat** — building more system is itself the main trap. First versions stay deliberately dumb and manual. If you find yourself growing the meta-system instead of doing your real work, stop.

## Limitations (read before adopting)

Loom is useful, but it is **not** magic. Honest trade-offs:

1. **Token cost.** Pulling your context in every turn (and the initial `/loom` scan) spends more tokens than vanilla Claude Code. The personalization isn't free.
2. **Cold start.** A fresh install does almost nothing — the payoff only shows up after you've fed it rules and cards for a while. Early on it feels underwhelming.
3. **Backward-looking; you drive evolution.** Loom is built from your *past*. It won't know a new technique exists, or that you've changed your mind, unless you tell it. It does **not** self-improve — every change is yours to make and approve.
4. **Keyword recall misses.** Cards surface by keyword match, so a natural-language prompt that avoids the trigger words won't pull the relevant note. Recall is best-effort.
5. **Stale memory sticks.** A wrong or outdated note keeps getting re-applied until *you* notice and fix it — confident answers built on a bad memory are a real risk.
6. **Single-identity precondition.** Loom fits one *coherent* worldview — that can be a person, a company, or a nation, but it must be internally consistent. If conflicting value systems are mixed together, the rules collide and the assistant can't tell which side it's on. Not a fit for that case.

## Install (overview)

1. Clone this repo.
2. Place `hooks/`, `skills/`, `output-styles/` under your `~/.claude/` directory.
3. Register the hooks in `~/.claude/settings.json` (see `INSTALL.md`).
4. Fill in your own personal layer (rules, cards) — these are gitignored by design.

Requires `python3` on your PATH (the hooks are Python). Built and tested on Windows; the bash hook may need tweaks on macOS/Linux.

⚠️ **Hooks run code on your machine automatically.** Read each hook before enabling it. This is opt-in by design — see `INSTALL.md`.

## A note on language

`loom/LOOM.md` is the **author's personal design canon, written in Korean and left untranslated** — it's the original design record, not user-facing docs. You don't need to read it to use Loom; this README and `INSTALL.md` are the English entry points.

The *structure* is language-agnostic — translate the rules/cards to your own language as you fill them in. A few defaults encode Korean-specific assumptions (e.g. the answer-lint hook's notes about 존댓말/반말 — formal vs. casual speech levels) that are **meaningless for English** and should simply be replaced with your own preferences.

## Status

Reference implementation, shared as-is. Not actively maintained as a product — it's a personal system opened up so others can borrow the patterns. Issues/PRs may go unanswered.

## Credits

- `skills/humanizer` is vendored from [blader/humanizer](https://github.com/blader/humanizer) (MIT) — see its own LICENSE.

## License

MIT — see [LICENSE](LICENSE).
