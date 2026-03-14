# Memory Page Redesign: L0-L4 Architecture

> Date: 2026-03-14
> Status: Approved

## Overview

Redesign the frontend Memory page to align with the new L0-L4 memory architecture defined in `backend/docs/memory-system-design.md` and `docs/project-overview.md`.

## Problem Statement

The current `Events.tsx` displays the old L1-L5 architecture:
- L1: Raw Events
- L2: Event Relations
- L3: Semantic Embeddings
- L4: Summaries
- L5: Capabilities

The backend has been rewritten to use the new L0-L4 lifecycle-based architecture:
- L0: Working Memory (session, goals, active entities)
- L1: Event Stream (normalized events)
- L2: Structured Cognition (knowledge graph + ToM assertions)
- L3: Reflection Memory (summaries + insights)
- L4: Procedural Memory (skills + strategies + circuit breakers)

## Goals

1. Update frontend to display L0-L4 architecture
2. Add backend API endpoints for missing layers
3. Remove outdated L5 (merged into L4)
4. Provide Session & Goals view for L0

## Non-Goals

1. Historical data migration
2. Backward compatibility with old API format
3. Advanced knowledge graph visualization (future enhancement)

## Architecture Mapping

| Tab | Old | New | Icon | Description |
|-----|-----|-----|------|-------------|
| 1 | L1 Raw Events | L0 Working Memory | Brain | Active sessions, goal stack, active entities |
| 2 | L2 Relations | L1 Event Stream | Database | Normalized event stream with filters |
| 3 | L3 Embeddings | L2 Cognition | Network | Knowledge graph triples + ToM assertions |
| 4 | L4 Summaries | L3 Reflection | FileText | Temporal/thematic summaries + insights |
| 5 | L5 Capabilities | L4 Procedural | Zap | Skills, strategies, circuit breaker states |

## Backend API Changes

### New Endpoints

```
# L0 Working Memory
GET /memory/l0/sessions              # List active sessions
GET /memory/l0/workbench/{session_id} # Get session workbench (goals, entities, tactics)

# L2 Structured Cognition
GET /memory/l2/statistics            # Get L2 stats (relations, assertions)
GET /memory/l2/relations             # List knowledge graph relations
GET /memory/l2/assertions            # List ToM assertions

# L3 Reflection Memory
GET /memory/l3/summaries             # List summaries with type filter
```

### Updated Endpoints

```
GET /memory/statistics               # Return new format with l0-l4 keys
DELETE /memory/clear                 # Update to clear l0-l4 instead of l1-l5
```

### Statistics Response Format

```json
{
  "l0": {
    "active_sessions": 1,
    "total_goals": 3,
    "total_entities": 5,
    "total_tactics": 2
  },
  "l1": {
    "event_count": 1234,
    "db_path": "~/.magi/data/events.db"
  },
  "l2": {
    "relation_count": 56,
    "assertion_count": 12,
    "db_path": "~/.magi/data/memories/l2_cognition.db"
  },
  "l3": {
    "summary_count": 8,
    "db_path": "~/.magi/data/memories/l3_reflections.db"
  },
  "l4": {
    "skill_count": 23,
    "open_circuit_breakers": 2,
    "db_path": "~/.magi/data/memories/l4_procedural.db"
  }
}
```

## Frontend Changes

### File Changes

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/pages/Events.tsx` | Rewrite | Complete rewrite with L0-L4 tabs |
| `frontend/src/pages/Memory.tsx` | Update | Update wrapper component |
| `frontend/src/api/modules/memory.ts` | Update | New API interfaces |
| `frontend/src/locales/en/app.json` | Update | English translations |
| `frontend/src/locales/zh/app.json` | Update | Chinese translations |

### Component Structure

```tsx
<MemoryPage>
  <Tabs>
    <TabsList>
      <L0Tab /> {/* Working Memory */}
      <L1Tab /> {/* Event Stream */}
      <L2Tab /> {/* Cognition */}
      <L3Tab /> {/* Reflection */}
      <L4Tab /> {/* Procedural */}
    </TabsList>

    <TabsContent value="l0">
      <L0WorkingMemory />
    </TabsContent>
    <TabsContent value="l1">
      <L1EventStream />
    </TabsContent>
    <TabsContent value="l2">
      <L2Cognition />
    </TabsContent>
    <TabsContent value="l3">
      <L3Reflection />
    </TabsContent>
    <TabsContent value="l4">
      <L4Procedural />
    </TabsContent>
  </Tabs>
</MemoryPage>
```

### L0 Working Memory View

Display components:
1. **Session Cards**: List active sessions with status, start time, last active
2. **Goal Stack**: Kanban-style view with pending/in_progress/completed columns
3. **Active Entities**: Card grid showing loaded entities with relevance scores
4. **Temporary Tactics**: List of short-lived tactics with expiration

### L1 Event Stream View

Enhancements over current:
1. Keep existing event list with expandable details
2. Add filters for `memory_domain` (user_authored, interaction, external_activity, etc.)
3. Add filter for `retention_class` (permanent, compressible, disposable)

### L2 Cognition View

Two sub-tabs:
1. **Knowledge Graph**: List of (subject, predicate, object) triples with confidence
2. **ToM Assertions**: List of assertions with validation_state, confidence_score

### L3 Reflection View

1. Summary list with type badges (temporal, thematic, insight)
2. Time range filter for temporal summaries
3. Topic filter for thematic summaries

### L4 Procedural View

1. Skill list merged from old L5 capabilities
2. Circuit breaker status indicator (closed/open/half-open)
3. Success rate visualization
4. Category filter (tool, api, workflow, strategy)

## Clear Memory Dialog Update

Update warning text to reflect new architecture:

```
This will permanently delete:
- L0 working context (sessions, goals)
- L1 event stream
- L2 cognition (knowledge graph, ToM assertions)
- L3 reflection summaries
- L4 procedural skills
- Chat context history
```

## Implementation Order

1. Backend: Add L0/L2/L3 endpoints
2. Backend: Update statistics and clear endpoints
3. Frontend: Update API module
4. Frontend: Rewrite Events.tsx
5. Frontend: Update translations
6. Testing: Manual verification

## Testing Checklist

- [ ] L0 displays active sessions and goal stack
- [ ] L1 events load with new filters
- [ ] L2 shows knowledge graph relations
- [ ] L2 shows ToM assertions with validation states
- [ ] L3 summaries display correctly
- [ ] L4 skills display with circuit breaker status
- [ ] Clear memory removes all layers
- [ ] Statistics show correct counts for all layers
- [ ] i18n works for both en/zh

## Risks

1. L0 may have no active sessions if backend just restarted
2. L2/L3 data may be empty if extraction not yet run
3. Old L5 capabilities data needs migration strategy to L4

## Follow-up

1. Add knowledge graph visualization (D3.js or similar)
2. Add L0 checkpoint restore UI
3. Add manual L3 summary generation trigger
