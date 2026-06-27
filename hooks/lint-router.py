#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# LINT v3 — situational router + hierarchical knowledge-card loader (UserPromptSubmit hook)
# Two parts:
#   (1) Four inline behavior locks: quick-question / explain-simply / debugging /
#       decided. Situational behavior guidance.
#   (2) Hierarchical knowledge-card loader (loom/cards/*.md): short docs injected as
#       context when their frontmatter matches the prompt. Multiple matching cards
#       accumulate (capped at MAX_CARDS) = "read several related docs at once".
#
# v3 retrieval design (why it's more than substring matching):
#   - anchor vs facet split: generic words (bug/todo/wip/etc.) are FACETS — they
#     can't summon a card on their own (kills over-firing), they only add points to
#     a card already matched by an anchor.
#   - multi-word triggers: full-phrase match = bonus; partial token match scored by
#     coverage, BUT a 2-word trigger needs BOTH tokens (so "skill card" isn't pulled
#     by a bare "skill" in an unrelated prompt).
#   - IDF weighting: common triggers score low, rare ones high.
#   - HIERARCHY (optional): cards may carry domain/area/kind frontmatter. A prompt
#     that names an `area` ranks that area's cards first, then a `kind` cue picks
#     which of them; ambiguous across areas -> a "clarify" hint.
#   - min-score cut + MAX_CARDS cap so unrelated cards aren't force-filled.
# On failure it passes silently (exit 0) so the hook never breaks the conversation.
import sys
import os
import json
import glob
import re
import math
from collections import deque, Counter

# ============================================================================
# CONFIG — paths and vocab. The word lists below are EXAMPLES (English). Replace
# or extend them with your own language / phrasing. They are the only parts that
# encode "who you are"; the engine logic around them is language-agnostic.
# ----------------------------------------------------------------------------
# Where the knowledge cards live. Change this if your cards are elsewhere.
CARD_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "loom", "cards"
)

# GLOBAL_FACETS: generic "status / media" words that should NOT summon a card by
# themselves (they over-fire because many cards share them). They only add a small
# bonus to a card already matched by a real anchor. EDIT to your own vocabulary.
GLOBAL_FACETS = {
    "bug", "todo", "wip", "fixme", "status", "progress", "done", "draft",
    "vfx", "sfx", "bgm", "sound", "animation", "anim", "fx", "widget", "ui",
}

# KIND_CUES (optional, for the hierarchy feature): if you split each topic into
# kinds (e.g. spec / design / status / polish), list the words a prompt uses to
# mean each kind. Leave empty ({}) to disable kind-level discrimination.
# The keys here must match the `kind:` values in your card frontmatter.
# EXAMPLE below uses a generic spec/design/status/polish scheme — replace freely.
KIND_CUES = {
    "spec":   ["spec", "value", "number", "intent", "balance", "how much"],
    "design": ["design", "code", "class", "architecture", "structure", "function"],
    "status": ["status", "bug", "todo", "now", "left", "stuck", "broken",
               "why", "doesn't work", "fix", "how far"],
    "polish": ["polish", "vfx", "sfx", "sound", "anim", "widget", "feedback", "fx"],
}
# When a prompt names an area but gives no kind cue, prefer this kind as default.
DEFAULT_KIND = "status"
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
DETAIL_RE = re.compile(
    r"\b(in[ -]?depth|in (?:more |greater |full )?detail|more detail|"
    r"greater detail|full detail|elaborate|verbose|"
    r"full explanation|step[ -]by[ -]step|comprehensive)\b"
)
if not DETAIL_RE.search(pl):
    hints.append("[concise mode — default/always] Until the user asks for detail, keep every answer to the essentials and easy to read: 1-line conclusion -> at most 3 key points (plain words) -> 1 line of next action. No long explanations, table spam, jargon, or number dumps.")

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

# ── Knowledge-card loader ──
MAX_CARDS = 8
MAX_HOPS = 2
MIN_SCORE = 1.0   # cards below this score are cut (noise guard); tune per IDF scale
LINK_RE = re.compile(r"\[\[\s*([^\]\|]+?)\s*(?:\|[^\]]*)?\]\]")


def _split_list(s):
    return [k.strip().strip("[]").strip().lower() for k in s.split(",") if k.strip().strip("[]").strip()]


def _parse_card(text, stem):
    triggers, facets, name, body, status, aliases = [], [], "", text.strip(), "", []
    domain, area, kind = "", [], ""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        # closing '---' must be a line that is exactly '---' (avoid body '---')
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body = "\n".join(lines[i + 1:]).strip()
                for line in lines[1:i]:
                    s = line.strip()
                    low = s.lower()
                    if low.startswith("triggers:"):
                        triggers = _split_list(s.split(":", 1)[1].strip().strip("[]"))
                    elif low.startswith("facets:"):
                        facets = _split_list(s.split(":", 1)[1].strip().strip("[]"))
                    elif low.startswith("aliases:"):
                        aliases = _split_list(s.split(":", 1)[1].strip().strip("[]"))
                    elif low.startswith("name:"):
                        name = s.split(":", 1)[1].strip()
                    elif low.startswith("status:"):
                        status = s.split(":", 1)[1].strip().lower()
                    elif low.startswith("domain:"):
                        domain = s.split(":", 1)[1].strip().lower()
                    elif low.startswith("area:"):
                        area = _split_list(s.split(":", 1)[1].strip().strip("[]"))
                    elif low.startswith("kind:"):
                        kind = s.split(":", 1)[1].strip().lower()
                break
    keys = set()
    if stem:
        keys.add(stem.lower())
    if name:
        keys.add(name.lower())
    for a in aliases:          # aliases double as link keys
        keys.add(a)
    if status in ("draft", "wip"):
        body = "[!][draft/unverified card — do not treat as fact, reference only] " + body
    links = [m.strip().lower() for m in LINK_RE.findall(body)]
    # anchor (real keyword) vs facet (generic word): a trigger that is a global
    # facet or listed in this card's facets: is treated as a facet.
    facet_set = set(facets) | GLOBAL_FACETS
    anchors = [t for t in triggers if t not in facet_set]
    card_facets = [t for t in triggers if t in facet_set] + facets
    return {"keys": keys, "anchors": anchors, "facets": card_facets,
            "body": body, "links": links,
            "domain": domain, "area": [a.lower() for a in area], "kind": kind}


cards = []
try:
    for path in sorted(glob.glob(os.path.join(CARD_DIR, "*.md"))):
        try:
            with open(path, encoding="utf-8-sig") as f:  # utf-8-sig = OK with BOM
                text = f.read()
        except Exception:
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        c = _parse_card(text, stem)
        if c["body"]:
            cards.append(c)
except Exception:
    cards = []

N = max(len(cards), 1)

# link name (name/filename/alias) -> card index
key_index = {}
for idx, c in enumerate(cards):
    for k in c["keys"]:
        key_index.setdefault(k, idx)


def _tokens(trigger):
    return [t for t in re.split(r"\s+", trigger.strip()) if t]


# Latin (alnum) tokens use word boundaries (so "lint" doesn't match "flint");
# non-Latin (e.g. CJK) keeps substring matching (weak word-boundary concept).
def _match(token, text):
    t = token.strip()
    if not t:
        return False
    if re.fullmatch(r"[a-z0-9 ._-]+", t):
        return re.search(r"(?<![a-z0-9._-])" + re.escape(t) + r"(?![a-z0-9._-])", text) is not None
    return t in text


# token document-frequency for IDF — common tokens (shared by many cards) weigh less.
token_df = Counter()
for c in cards:
    toks = set()
    for a in c["anchors"]:
        toks.update(_tokens(a))
    for t in toks:
        token_df[t] += 1


def _idf(token):
    df = token_df.get(token, 1)
    return math.log(1 + N / df)


# card score = anchor-match score (+ facet bonus only when an anchor matched).
def _anchor_score(anchor, text, facet_set):
    toks = _tokens(anchor)
    if not toks:
        return 0.0
    if len(toks) == 1:
        t = toks[0]
        if len(t) < 2 and not re.fullmatch(r"[a-z0-9]+", t):
            return 0.0
        return _idf(t) if _match(t, text) else 0.0
    # multi-word
    idf_sum = sum(_idf(t) for t in toks)
    if anchor in text:                       # full phrase, contiguous
        return idf_sum * 1.5
    hit = [t for t in toks if len(t) >= 2 and _match(t, text)]
    if not hit:
        return 0.0
    # at least one core token (non-facet) must match — blocks a bare facet word
    # hidden inside a multi-word trigger from summoning the card.
    if not any(t not in facet_set for t in hit):
        return 0.0
    # a 2-word trigger needs BOTH tokens (else "skill card" is pulled by bare "skill").
    if len(toks) == 2 and len(hit) < 2:
        return 0.0
    cov = len(hit) / len(toks)
    if len(hit) >= 2 or cov >= 0.5:          # 3+ words: half-coverage is enough
        return sum(_idf(t) for t in hit)
    return 0.0


# ── Hierarchy (domain/area/kind) — optional; active only if cards carry `area` ──
AREA_VOCAB = set()
for c in cards:
    for a in c["area"]:
        if a and len(a) >= 2:      # no 1-char areas (short substring over-fire guard)
            AREA_VOCAB.add(a)
prompt_areas = {a for a in AREA_VOCAB if _match(a, pl)}
prompt_kinds = {k for k, cues in KIND_CUES.items() if any(cu in pl for cu in cues)}

# Ranking: (1) area-matched cards first, (2) kind-cue match, (3) keyword score,
# (4) original order. i.e. "narrow by area, then discriminate by kind".
scored = []
for idx, c in enumerate(cards):
    facet_set = set(c["facets"]) | GLOBAL_FACETS
    a_score = sum(_anchor_score(a, pl, facet_set) for a in c["anchors"])
    card_areas = set(c["area"])
    area_hit = bool(card_areas & prompt_areas)
    if a_score <= 0 and not area_hit:
        continue                              # candidate = keyword OR area match
    f_score = 0.0
    for f in c["facets"]:
        if _match(f, pl):
            f_score += 0.3
    f_score = min(f_score, 0.9)
    total = a_score + f_score
    if area_hit:
        if prompt_kinds:
            kind_rank = 2 if c["kind"] in prompt_kinds else 0
        else:
            kind_rank = 1 if c["kind"] == DEFAULT_KIND else 0
    else:
        kind_rank = 0
    if total >= MIN_SCORE or area_hit:        # area-matched cards bypass MIN_SCORE
        scored.append((1 if area_hit else 0, kind_rank, total, idx))

scored.sort(key=lambda x: (-x[0], -x[1], -x[2], x[3]))
scored = [(t, idx) for _ah, _kr, t, idx in scored]

# 1) take scored seeds first; 2) if room remains, expand via [[links]] (BFS).
visited = set()
ordered_bodies = []
link_queue = deque()
for _score, idx in scored:
    if len(ordered_bodies) >= MAX_CARDS:
        break
    if idx in visited:
        continue
    visited.add(idx)
    ordered_bodies.append(cards[idx]["body"])
    for link in cards[idx]["links"]:
        t = key_index.get(link)
        if t is not None and t not in visited:
            link_queue.append((t, 1))
while link_queue and len(ordered_bodies) < MAX_CARDS:
    idx, hop = link_queue.popleft()
    if idx in visited:
        continue
    visited.add(idx)
    ordered_bodies.append(cards[idx]["body"])
    if hop < MAX_HOPS:
        for link in cards[idx]["links"]:
            t = key_index.get(link)
            if t is not None and t not in visited:
                link_queue.append((t, hop + 1))

# Clarify hint: several areas matched but no kind cue to narrow -> ask which one.
# Cards are still loaded (fallback kept, no wrong-context cost); this only adds a hint.
# High threshold (2+ areas AND zero kind cue) so it fires rarely (avoid over-asking).
if ordered_bodies and len(prompt_areas) >= 2 and not prompt_kinds:
    hints.append(
        "[clarify — ambiguous area] The prompt seems to span multiple areas (%s) "
        "with no cue for which kind (spec/design/status/polish). Before answering, "
        "ask in ONE line which one the user means. Skip if it's actually clear."
        % ", ".join(sorted(prompt_areas))
    )

# If any card is loaded, prepend a one-line "compliance rule".
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
