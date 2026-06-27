#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# LINT v2 — situational router + cumulative knowledge-card loader (UserPromptSubmit hook)
# Two parts:
#   (1) Four inline behavior locks: quick-question / explain-simply / debugging /
#       decided. Situational behavior guidance.
#   (2) Cumulative knowledge-card loader (loom/cards/*.md): short docs injected as
#       context. If a card's frontmatter `triggers` keyword matches the input, that
#       card's body is injected into the answer. Multiple matching cards accumulate
#       (capped at MAX_CARDS) = "read several related docs at once, then answer".
#       Keywords are hints, not commands — ignored when context doesn't fit.
# On failure it passes silently (exit 0) so the hook never breaks the conversation.
import sys
import os
import json
import glob
import re
from collections import deque

# ============================================================================
# CONFIG — paths and trigger words. The trigger words used by the behavior
# locks below are EXAMPLES (English). Replace or extend them with your own
# language / phrasing. Korean equivalents from the original author have been
# moved into comments as examples only; add your own as needed.
# ----------------------------------------------------------------------------
# Where the knowledge cards live. Change this if your cards are elsewhere.
CARD_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "loom", "cards"
)
# ============================================================================

try:
    data = json.load(sys.stdin)
    prompt = str(data.get("prompt", ""))
except Exception:
    sys.exit(0)  # parse failure = fall back to normal behavior

p = prompt.strip()
pl = p.lower()
hints = []

# NOTE: trigger words in each lock below are EXAMPLES. Edit them to match how
# you actually phrase things. Markers like [!] are plain ASCII on purpose
# (emoji can render as garbage in some terminals).

# ── Default "concise mode" (always on until the user asks for detail) ──
# Use explicit phrases / word boundaries so generic phrasings like
# "implementation detail", "detailed error", "the details of the bug" do NOT
# accidentally turn concise mode off. Only an explicit request for more depth does.
DETAIL_RE = re.compile(
    r"\b(in[ -]?depth|in (?:more |greater |full )?detail|more detail|"
    r"greater detail|full detail|elaborate|verbose|"
    r"full explanation|step[ -]by[ -]step|comprehensive)\b"
)
if not DETAIL_RE.search(pl):
    hints.append("[concise mode — default/always] Until the user asks for detail, keep every answer to the essentials and easy to read: 1-line conclusion -> at most 3 key points (plain words) -> 1 line of next action. No long explanations, table spam, jargon, or number dumps. If it gets long, move it to a document and keep the screen to a summary.")

# ── Behavior lock 1: quick question (speed) ──
if any(k in pl for k in ["quick:", "quick question", "tl;dr", "tldr", "briefly",
                         "in short", "just answer", "short answer"]):
    hints.append("[quick question — LINT] Answer immediately. No heavy tools (cross-check CLI, workflows, background jobs, multi-file operations). Just the next single step, short and simple.")

# ── Behavior lock 2: "explain simply" / confusion signal (lower the tone) ──
if any(k in pl for k in ["explain simply", "in plain", "i don't understand",
                         "dont understand", "what do you mean", "confused",
                         "eli5", "make it simple"]):
    hints.append("[simple mode — LINT] [!] Stop the jargon, code identifiers, cards, and long text. Explain from the start in plain words with concrete examples. Confirm understanding before moving on.")

# ── Behavior lock 3: debugging (force root-cause) ──
if any(k in pl for k in ["doesn't work", "doesnt work", "not working", "crash",
                         "error", "bug", "broken", "fails", "exception",
                         "stack trace"]):
    hints.append("[debugging — LINT] Root cause first: investigate -> hypothesize -> verify, then fix. No guess-patching or covering symptoms. You must be able to explain why it was fixed. (Ignore if context shows it isn't a bug.)")

# ── Behavior lock 4: "decided / just do it" signal (proceed, one exception) ──
if any(k in pl for k in ["just do it", "go ahead", "ship it", "no more questions",
                         "decided", "stop asking", "do it now", "just build it"]):
    hints.append("[decided signal — LINT] The decision is made. Stop second-guessing and just proceed. If you spot a genuinely critical problem, raise it once briefly; if it's still decided, proceed immediately.")

# ── Knowledge-card cumulative loader + link (web) following ──
# (1) When a `triggers` keyword matches the input, take that card as an entry point.
# (2) Follow [[links]] in its body to also inject cards that must be connected (cumulative).
#   Link identity = frontmatter 'name:' or filename (stem). Up to MAX_HOPS hops,
#   total cap MAX_CARDS (token-explosion guard).
MAX_CARDS = 8
MAX_HOPS = 2
# CARD_DIR is defined in the CONFIG block at the top of this file.
LINK_RE = re.compile(r"\[\[\s*([^\]\|]+?)\s*(?:\|[^\]]*)?\]\]")


def _parse_card(text, stem):
    triggers, name, body, status = [], "", text.strip(), ""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        # closing '---' must be a line that is exactly '---' (avoid matching '---' in body)
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body = "\n".join(lines[i + 1:]).strip()
                for line in lines[1:i]:
                    s = line.strip()
                    low = s.lower()
                    if low.startswith("triggers:"):
                        triggers = [k.strip().lower() for k in s.split(":", 1)[1].split(",") if k.strip()]
                    elif low.startswith("name:"):
                        name = s.split(":", 1)[1].strip()
                    elif low.startswith("status:"):
                        status = s.split(":", 1)[1].strip().lower()
                break
    keys = set()
    if stem:
        keys.add(stem.lower())
    if name:
        keys.add(name.lower())
    if status in ("draft", "wip", "초안"):  # keep legacy input values for back-compat
        body = "[!][draft/unverified card — do not treat as fact, reference only] " + body
    links = [m.strip().lower() for m in LINK_RE.findall(body)]
    return {"keys": keys, "triggers": triggers, "body": body, "links": links}


cards = []
try:
    for path in sorted(glob.glob(os.path.join(CARD_DIR, "*.md"))):
        try:
            with open(path, encoding="utf-8-sig") as f:  # utf-8-sig = OK even with BOM
                text = f.read()
        except Exception:
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        c = _parse_card(text, stem)
        if c["body"]:
            cards.append(c)
except Exception:
    cards = []

# link name (name/filename) -> card index
key_index = {}
for idx, c in enumerate(cards):
    for k in c["keys"]:
        key_index.setdefault(k, idx)

# seed (entry) = trigger-matched cards -> BFS following links from there
queue = deque()
for idx, c in enumerate(cards):
    if any(k and k in pl for k in c["triggers"]):
        queue.append((idx, 0))

visited = set()
ordered_bodies = []
while queue and len(ordered_bodies) < MAX_CARDS:
    idx, hop = queue.popleft()
    if idx in visited:
        continue
    visited.add(idx)
    ordered_bodies.append(cards[idx]["body"])
    if hop < MAX_HOPS:
        for link in cards[idx]["links"]:
            t = key_index.get(link)
            if t is not None and t not in visited:
                queue.append((t, hop + 1))

# If any card is loaded, prepend a one-line "compliance rule" to its body.
if ordered_bodies:
    hints.append(
        "[card compliance rule] The [knowledge—] cards above/below are confirmed "
        "knowledge about the user. (1) Match your answer to the card content "
        "(don't read and ignore). (2) Don't contradict the cards. (3) Don't "
        "invent facts not grounded in the cards; if you don't know, say "
        "'not grounded in the cards'."
    )

for b in ordered_bodies[:MAX_CARDS]:
    hints.append(b)

for h in hints:
    print(h)

sys.exit(0)
