# CKSKILL Integration

Nove compiles the reusable writing rules under `CKSKILL/` into typed runtime
contracts. The application does not execute arbitrary scripts from imported
skill directories and does not paste whole `SKILL.md` files into prompts.

## Runtime Ruleset

Current ruleset: `2026.07`.

The authoritative runtime implementation is `apps/api/app/craft.py`. Every
writing contract includes a `provenance` list with stable `ruleId`, source path,
source line, scope, and severity. The first compiled sources are:

- `webnovel-write/SKILL.md`: taskbook order, one review round, targeted repair,
  Anti-AI check, prewrite/precommit/postcommit gates.
- `webnovel-plan/SKILL.md`: time anchors, chapter span, countdown, obstacle,
  cost, CBN/CPNs/CEN, mandatory nodes, forbidden zones, and chapter-end open
  questions.
- `webnovel-review/SKILL.md`: evidence-based blocking findings and explicit
  author override.
- `webnovel-init/SKILL.md`: protagonist desire/flaw, world scale, power system,
  golden-finger cost, anti-trope, hard constraints, reader, and platform.
- `webnovel-learn/SKILL.md`: append-only project writing patterns.
- `webnovel-doctor/SKILL.md`: read-only, phase-aware health reporting.
- `oh-story/story-deslop`: expression-only repair, reasoning-chain density,
  sentence stutter, over-compressed prose, abstract endings, cliche density,
  formal notice language, and Anti-AI protection.
- `Humanizer-zh`: high-frequency AI vocabulary and mechanical language-pattern
  checks, adapted for fiction rather than copied as a generic rewrite prompt.
- `zaomeng/validation_policy`: no silent repair for low-confidence canon
  conflicts.

The other CKSKILL repositories were treated as research/reference assets. A
rule enters the executable ruleset only after it has a deterministic or typed
implementation and a regression test. Demo files, archives, screenshots, and
vendor code never override the runtime ruleset.

## Writing Flow

```text
creative profile
  -> blueprint preview and author confirmation
  -> volume/arc/chapter outline
  -> planning gate
  -> prewrite gate
  -> ordered writing taskbook
  -> scene beats
  -> candidate draft
  -> deterministic continuity/craft checks
  -> one audit round
  -> targeted repair or one explicit rewrite candidate
  -> author accepts candidate
  -> confirmation quality gate
  -> facts, state, summaries, memory, and vector projection
```

AI output is always a candidate version. It never overwrites the current
editor version. Confirmed versions remain the only source for story memory.

## Creative Profile

`Novel.writing_profile` stores the project constitution:

- target audience and platform;
- protagonist name, desire, and consequence-producing flaw;
- world scale and power system;
- golden finger/core ability and its cost or boundary;
- antagonist mirror;
- anti-trope constraint;
- at least two verifiable hard constraints;
- project Anti-AI patterns and learned writing patterns;
- `strict_workflow` compatibility mode.

New projects use strict mode. Existing and imported projects default to
compatible mode so the migration does not block old work. Authors can enable
strict mode from `Project Settings -> Writing Rules` after completing the
profile and chapter outlines.

## Chapter Contract

`GET /api/chapters/{chapter_id}/writing-contract` returns a versioned contract
with a five-part taskbook in fixed priority order:

1. `chapter_directive`: goal, conflict/obstacle, cost, time anchor, chapter
   span, previous gap, countdown, and chapter-end open question.
2. `story_nodes`: exactly one CBN, two to four ordered CPNs, one CEN, and at
   most four mandatory nodes.
3. `forbidden_zones`: at most five chapter-specific hard prohibitions.
4. `style_guidance`: genre guidance, protagonist-flaw guard, anti-trope, hard
   constraints, Anti-AI patterns, learned patterns, and author style options.
5. `dynamic_context`: recent confirmed summaries, open plot threads, structured
   character/location states, the previous chapter CEN/open question, and the
   retrieval manifest.

Dynamic context can supplement the first four sections but cannot override
them. Locked world rules are never dropped by the context budgeter.

## Gates

Planning gate:

- strict chapter outlines cannot be committed with missing contract fields;
- placeholder text such as `[待补充]`, `暂名`, `{占位}`, or `{章纲目标}` blocks;
- CPN count, mandatory-node count, and forbidden-zone count are bounded.

Prewrite gate:

- the generation API rejects a strict chapter before creating a job when its
  contract is blocked;
- the background job repeats the check to prevent queued jobs from bypassing a
  later policy change;
- failed or cancelled generation restores the chapter state.

Audit gate:

- deterministic checks run even when no audit model is configured;
- placeholders, engineering field leakage, forbidden events, removed locked
  text, canon conflicts, and missing mandatory nodes are blocking findings;
- Anti-AI checks report locatable evidence for repeated empty cognition,
  mechanical contrast, empty summaries, uncertain modifiers, mechanical
  progression, paragraph isomorphism, dense reasoning chains, metaphor and
  em-dash overuse, abstract trailer endings, formal notice language,
  consecutive sentence stutter, and over-compressed short paragraphs;
- every finding carries a stable `ruleId`, `blocking` flag, bounded
  `confidence`, and structured `location` in addition to author-facing
  evidence and repair guidance;
- configured audit dimensions total 100 and include timeline and AI traces.

Confirmation gate:

- strict projects require an audit for the current version;
- non-PASS, fatal, or blocked-contract confirmation requires an author reason
  of at least eight characters;
- the override reason, audit decision, gate state, and ruleset are stored in
  `ChapterVersion.content_json.qualityGateOverride`;
- successful confirmation updates story memory and structured state.

## API and UI

- `GET /api/chapters/{id}/writing-contract`: chapter taskbook and prewrite gate.
- `GET /api/novels/{id}/writing-health`: read-only project health summary.
- `POST /api/novels/{id}/writing-patterns`: append a learned project pattern.
- `PATCH /api/novels/{id}`: update `writing_profile`.

The new-novel wizard collects the strict creative profile. The blueprint editor
exposes reader/creative constraints. The outline editor exposes the full
chapter contract. The writing workspace displays the gate and taskbook. Project
settings provides profile editing and health counters.

## Verification

The automated suite proves:

- complete strict contracts pass and incomplete/placeholder contracts block;
- deterministic review blocks placeholders, engineering leakage, and missing
  mandatory nodes;
- locked rules survive extreme context pressure;
- strict outline commit rejects incomplete chapter contracts;
- strict confirmation cannot skip the current-version audit;
- existing API, memory, outline, version, audit, and frontend workflows remain
  green in compatible mode.
