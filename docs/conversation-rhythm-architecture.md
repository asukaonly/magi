# Conversation Rhythm Architecture

## Purpose

Conversation rhythm lets one assistant turn appear as several natural chat
bubbles without making the user-visible contract depend on JSON or
provider-specific streaming tricks.

The goal is not to make replies longer. The goal is to preserve a single
canonical answer while giving the chat surface a more human-feeling cadence:
a short acknowledgement, a focused answer, and an optional next-step or
afterthought when the answer naturally supports that shape.

## Product Principles

- The core answer remains authoritative. Segmentation must not invent facts,
  alter the assistant's stance, or change the user's requested language.
- Multi-bubble output is a presentation choice for a single assistant turn, not
  multiple independent assistant turns.
- Every visible segment must carry real information or conversational value.
  Empty filler, fake hesitation, and forced follow-up questions are product bugs.
- Simple factual requests should stay single-message by default.
- Structured technical answers should stay single-message by default when they
  contain numbered lists, command or config details, tables, stack traces, or
  dense implementation mechanics. In these cases the internal structure already
  provides reading rhythm, and splitting into separate chat bubbles can hurt
  scanning, copying, and later reference.
- Short or compact answers should not be split into many bubbles. More than
  three segments should be reserved for highly conversational, persona-appropriate
  turns with several distinct moves.
- Technical answers that are not structurally protected are governed by the main
  reply pacing prompt, not by an expanding backend keyword taxonomy. The model
  should keep them single-message unless a split preserves the technical body
  and clearly improves conversational flow.
- Non-initial rhythm segments should wait at least one second before appearing;
  sub-second delays read as UI animation rather than conversational cadence.
- The feature must degrade to the existing single-message flow whenever
  segmentation, validation, persistence, or notification fails.

## Main Flow

```text
User message
-> intent and tool routing
-> direct LLM / tool loop / orchestration render
-> canonical assistant answer text with optional internal bubble markers
-> backend segmentation parser
-> validated response plan
-> chat outcome writer emits one or more visible assistant messages
```

Segmentation is deliberately placed after the main execution handler. This keeps
direct chat, function calling, and orchestration rendering on the same contract:
handlers produce `ExecutionResult.response_text`; presentation logic decides
whether that text is surfaced as one message or several messages.

## Model Responsibilities

### Main Model

The main model answers the user's request normally. When conversation rhythm is
enabled, it may use the internal marker `‖` to indicate chat-bubble boundaries.
The marker is not user-facing content and must never be explained to the user.

Recommended behavior:

- reply in the user's language
- put the core answer early
- use compact semantic paragraphs when the task is substantive
- keep lightweight casual chat short
- never output JSON, message labels, or bubble metadata
- use `‖` only when the current turn genuinely benefits from multiple bubbles

### Backend Segmentation Parser

The parser is deterministic. It does not answer the user again and it does not
rewrite the reply. It only inspects the finished answer for the internal `‖`
marker and turns valid parts into visible message records.

Preferred contract:

- input: the canonical answer text, possibly containing `‖`
- output: two to six visible segments, plus computed delays
- no rewritten user-visible text during parsing

The backend reconstructs visible content by splitting the original answer. If
the split is invalid, empty, exceeds six segments, or targets protected
structure, the system falls back to one assistant message.

During parsing, the backend performs deterministic content-feature detection.
Code blocks, tables, command/config blocks, stack traces, and dense numbered or
bulleted lists bypass segmentation entirely. The backend does not try to
classify arbitrary prose as "technical" through keyword lists; semantic
technicality stays inside the main reply pacing prompt, where the model can
judge the whole user request and answer together.

When a split is rejected, the backend strips the internal marker before history,
memory, events, or external channels see the text. If the rejected split touched
protected line-oriented structure such as lists or code blocks, markers are
converted to line breaks so the original layout is preserved.

Triggering is persona-aware. Chatty or emotional turns may naturally use more
bubbles, while serious, task, analysis, and crisis turns should usually stay as
one message.

## Prompt Interaction With Chat Scenario

The default casual chat scenario historically enforced ultra-short replies. That
is incompatible with conversation rhythm when the user asks for architecture,
planning, emotional support, or multi-part help.

The prompt policy should distinguish sentence style from whole-answer length:

- lightweight casual chat can remain one or two short sentences
- substantive work should answer fully using compact semantic paragraphs
- each paragraph should perform one conversational move: acknowledge, answer,
  explain a trade-off, or suggest a next step

This keeps the product's instant-message tone while giving the model clear
semantic boundaries for where a bubble split is acceptable.

## Persistence Contract

`chat_turns` remains the owner of turn-level execution state and UX plan.

`chat_messages` may contain multiple visible assistant rows for the same
`turn_id` when rhythm segmentation is active. These rows use a rhythm-specific
message kind and carry a small payload with:

- segment index and count
- segment intent
- planned delay
- source segment IDs

The canonical full answer still feeds memory updates, runtime trace, and
assistant projection. It should not be replaced by concatenating notification
events on the frontend.

Turn-scoped supporting metadata should appear only once across visible rhythm
segments. Recalled-memory references belong on the terminal segment so they act
as a footer for the whole assistant turn instead of repeating inside every
bubble.

## Streaming Policy

Initial implementation should not stream segmented text.

When conversation rhythm is active:

- the main visible token stream is disabled for that turn, even if the streaming
  preference is otherwise enabled
- the frontend receives complete segment messages through normal chat message
  notifications

Future segment-level streaming may be added only after stream events carry a
stable segment identifier. Streaming by `turn_id` alone merges all chunks into a
single bubble and breaks the rhythm contract.

## MVP Scope

The first implementation supports:

- a hidden preference gate for enabling conversation rhythm
- main-model prompt guidance for inline bubble markers
- deterministic marker parsing with strict validation and single-message fallback
- up to six visible assistant segments per turn
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
