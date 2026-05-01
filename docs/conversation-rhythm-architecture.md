# Conversation Rhythm Architecture

## Purpose

Conversation rhythm lets one assistant turn appear as several natural chat
bubbles without making the core answer path depend on user-visible JSON or
provider-specific streaming tricks.

The goal is not to make replies longer. The goal is to preserve a single
canonical answer while giving the chat surface a more human-feeling cadence:
a short acknowledgement, a focused answer, and an optional next-step or
afterthought when the answer naturally supports that shape.

## Product Principles

- The core answer remains authoritative. Rhythm planning must not invent facts,
  alter the assistant's stance, or change the user's requested language.
- Multi-bubble output is a presentation choice for a single assistant turn, not
  multiple independent assistant turns.
- Every visible segment must carry real information or conversational value.
  Empty filler, fake hesitation, and forced follow-up questions are product bugs.
- Simple factual requests should stay single-message by default.
- The feature must degrade to the existing single-message flow whenever planning,
  validation, persistence, or notification fails.

## Main Flow

```text
User message
-> intent and tool routing
-> direct LLM / tool loop / orchestration render
-> canonical assistant answer text
-> internal rhythm planner
-> validated response plan
-> chat outcome writer emits one or more visible assistant messages
```

The rhythm planner is deliberately placed after the main execution handler. This
keeps direct chat, function calling, and orchestration rendering on the same
contract: handlers produce `ExecutionResult.response_text`; presentation logic
decides whether that text is surfaced as one message or several messages.

## Model Responsibilities

### Main Model

The main model answers the user's request normally. It should be prompted to
produce rhythm-friendly prose, not a presentation protocol.

Recommended behavior:

- reply in the user's language
- put the core answer early
- use compact semantic paragraphs when the task is substantive
- keep lightweight casual chat short
- never output JSON, hidden delimiters, message labels, or bubble metadata

### Rhythm Planner

The planner is an internal presentation model call. It is not allowed to answer
the user again.

Preferred contract:

- input: the canonical answer split into immutable text units
- output: JSON groups that reference unit IDs, plus intent labels and delays
- no rewritten user-visible text in the planner output

The backend reconstructs visible content from the original answer units. If the
planner output is invalid, references unknown units, drops too much content, or
exceeds limits, the system falls back to one assistant message.

When multiple units are grouped into one visible bubble, they are joined with a
single line break so the bubble keeps a readable cadence without introducing a
large paragraph gap.

Triggering should be language-aware. Chinese chat often carries multiple
semantic moves in fewer characters than English, so the planner uses a lower
minimum content threshold for CJK text and accepts sentence boundaries without
requiring spaces after punctuation. Short single-move replies still remain one
message.

## Prompt Interaction With Chat Scenario

The default casual chat scenario historically enforced ultra-short replies. That
is incompatible with rhythm planning when the user asks for architecture,
planning, emotional support, or multi-part help.

The prompt policy should distinguish sentence style from whole-answer length:

- lightweight casual chat can remain one or two short sentences
- substantive work should answer fully using compact semantic paragraphs
- each paragraph should perform one conversational move: acknowledge, answer,
  explain a trade-off, or suggest a next step

This keeps the product's instant-message tone while giving the rhythm planner
usable semantic boundaries.

## Persistence Contract

`chat_turns` remains the owner of turn-level execution state and UX plan.

`chat_messages` may contain multiple visible assistant rows for the same
`turn_id` when rhythm planning is active. These rows use a rhythm-specific
message kind and carry a small payload with:

- segment index and count
- segment intent
- planned delay
- source unit IDs

The canonical full answer still feeds memory updates, runtime trace, and
assistant projection. It should not be replaced by concatenating notification
events on the frontend.

## Streaming Policy

Initial implementation should not stream raw planner JSON or segment text.

When conversation rhythm is active:

- the main visible token stream is disabled for that turn, even if the streaming
  preference is otherwise enabled
- planner calls are non-streaming and internal
- the frontend receives complete segment messages through normal chat message
  notifications

Future segment-level streaming may be added only after stream events carry a
stable segment identifier. Streaming by `turn_id` alone merges all chunks into a
single bubble and breaks the rhythm contract.

## MVP Scope

The first implementation supports:

- a hidden preference gate for enabling conversation rhythm
- main-model prompt guidance for rhythm-friendly canonical answers
- internal JSON rhythm planning with strict validation and single-message fallback
- up to three visible assistant segments per turn
- complete-message notifications for each segment
- display-history support for rhythm segment messages

The MVP intentionally does not include:

- proactive conversation seeds
- detached presentation scheduling that survives restarts
- segment-level token streaming
- UI controls for rhythm intensity
- long-running cancellation of already persisted segments

## Follow-Up Architecture

Later phases should split execution completion from presentation completion:

- execution run: LLM/tool work is done and trace/memory can finalize
- presentation run: delayed visible segments may still be pending

A durable presentation scheduler can then cancel unsent segments when the user
speaks again, recover cleanly after restart, and expose user-facing controls for
concise, natural, or expressive rhythm.
