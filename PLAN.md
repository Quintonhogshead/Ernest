# Ernest — the plan

The full, designed vision for Ernest lives as an interactive document:

**→ https://claude.ai/code/artifact/ad412914-9328-4c52-9b23-d5eb3722f711**

It covers the operating principles, the complete capability set, the
architecture, the **trust ladder** (how each capability earns autonomy), the
prompt-injection firewall, **away mode** (the honeymoon test), the build roadmap,
and running costs. This file is a durable summary in case that link ever moves.

## What Ernest is

One agent, several scheduled jobs sharing one brain (prompts + policy), one
memory, one channel to you (Discord). It keeps your three worlds — work, school,
and the business — from colliding or falling on the floor. The loop:

> perceive → think → act (within policy) → report → remember

## Operating principles

1. **Trust is earned per capability, not granted globally.** Everything starts
   read-only. Drafting precedes sending; narrow sending precedes broad.
2. **Everything Ernest does is written down** — one append-only audit log; the
   evening wrap is generated from it.
3. **Inbound content is hostile until proven boring.** Email, invites, Canvas
   posts, news, and library chunks are untrusted data, never instructions.
4. **Boring reliability beats clever features.** Polling before webhooks, digests
   before real-time, SQLite before anything with a connection string.
5. **Ernest assists with school; it never does school.** Canvas is read-only,
   forever.

## The trust ladder

| Level | Meaning |
|---|---|
| L0 | Observe — read and log only |
| L1 | Summarize — digests and alerts, no side effects |
| L2 | Draft — proposals a human executes |
| L3 | Act on approval — one tap executes exactly what was shown |
| L4 | Autonomous within policy — acts first, reports in the evening wrap |

**This repository implements L0–L1** (plus the library and research desk, which
are read-only by nature). Everything L2+ — drafting, sending, booking, away mode
— is deliberately not here; it's judgment-heavy senior-model work gated behind
approval history.

## Capabilities (built vs. planned)

- **Built here:** email triage (3 accounts), Canvas sync, news desk, morning/
  evening briefs, the retrieval **library** (`ask`), the **research desk**,
  iMessage reader (macOS), Discord as the delivery channel.
- **Planned (see the artifact):** reply drafting in your voice, calendar concierge
  + meeting prep, interactive Discord approvals, meeting memory (record →
  transcribe → library), phone screening, overnight coding fleet, the
  remembrancer (birthdays + life admin + personal CRM), health & habits, and
  **away mode** for the honeymoon.

## Timeline

Wedding: **May 1, 2027.** The roadmap works backward so that away mode — routine
replies handled autonomously, everything else held, only genuine urgency
escalated — is built and rehearsed before then. The supervised months (tapping
[Send] on Ernest's drafts) are what make away mode trustworthy; there's no
shortcut around them.

## Hard lines — never, at any level

- Never moves money, makes purchases, or touches payment credentials.
- Never deletes — archive and label only.
- Never sends to a never-before-seen recipient without a tap.
- Never follows an instruction found *inside* a message, invite, post, or
  retrieved chunk.
- Never submits coursework, posts to Canvas, or messages instructors.
- Never handles a login page; never merges its own code; never records an
  unflagged meeting.
