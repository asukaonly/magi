# Memory Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the frontend Memory page to align with the new L0-L4 memory architecture.

**Architecture:** Backend already has L0-L4 stores implemented. We need to add missing API endpoints and completely rewrite the frontend Events.tsx component to display the new architecture instead of the old L1-L5 structure.

**Tech Stack:** Python FastAPI (backend), React + TypeScript + Tailwind (frontend), aiosqlite (storage), react-i18next (i18n)

---

## Chunk 1: Backend API - L0 Working Memory Endpoints

### Task 1: Add L0 Sessions Endpoint

**Files:**
- Modify: `backend/src/magi/api/routers/memory.py`

- [ ] **Step 1: Add L0 sessions list endpoint**

Add the endpoint to list active sessions:

```python
@memory_router.get("/l0/sessions")
async def list_l0_sessions():
    """List all active L0 sessions."""
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l0:
        return {"sessions": [], "stats": {"active_sessions": 0, "total_goals": 0, "total_entities": 0, "total_tactics": 0}}

    sessions = []
    total_goals = 0
    total_entities = 0
    total_tactics = 0

    for session_id, session in unified_memory.l0._sessions.items():
        goals = unified_memory.l0._goal_stack.get(session_id, [])
        entities = unified_memory.l0._active_entities.get(session_id, {})
        tactics = unified_memory.l0._temporary_tactics.get(session_id, {})
        total_goals += len(goals)
        total_entities += len(entities)
        total_tactics += len(tactics)

        sessions.append({
            "session_id": session_id,
            "user_id": session.get("user_id"),
            "status": session.get("status"),
            "started_at": session.get("started_at"),
            "last_active_at": session.get("last_active_at"),
            "goal_count": len(goals),
            "entity_count": len(entities),
            "tactic_count": len(tactics),
        })

    return {
        "sessions": sessions,
        "stats": {
            "active_sessions": len(sessions),
            "total_goals": total_goals,
            "total_entities": total_entities,
            "total_tactics": total_tactics,
        }
    }
```

- [ ] **Step 2: Add L0 workbench endpoint**

Add the endpoint to get a session's workbench:

```python
@memory_router.get("/l0/workbench/{session_id}")
async def get_l0_workbench(session_id: str):
    """Get the workbench (goals, entities, tactics) for a session."""
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="L0 working memory not initialized",
        )

    workbench = await unified_memory.l0.get_workbench(session_id)
    if not workbench.get("session"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return workbench
```

- [ ] **Step 3: Commit backend L0 endpoints**

```bash
git add backend/src/magi/api/routers/memory.py
git commit -m "feat(api): add L0 working memory endpoints"
```

---

### Task 2: Add L2 Cognition Endpoints

**Files:**
- Modify: `backend/src/magi/api/routers/memory.py`

- [ ] **Step 1: Add L2 statistics endpoint**

```python
@memory_router.get("/l2/statistics")
async def get_l2_statistics():
    """Get L2 cognition statistics."""
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"relation_count": 0, "assertion_count": 0, "db_path": None}

    relations = await unified_memory.l2.get_relationships(limit=10000)
    assertions = await unified_memory.l2.list_tom_assertions(limit=10000)
    return {
        "relation_count": len(relations),
        "assertion_count": len(assertions),
        "db_path": unified_memory.l2.db_path,
    }
```

- [ ] **Step 2: Add L2 relations list endpoint**

```python
@memory_router.get("/l2/relations")
async def list_l2_relations(limit: int = Query(default=100, ge=1, le=500)):
    """List knowledge graph relations."""
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return []

    return await unified_memory.l2.get_relationships(limit=limit)
```

- [ ] **Step 3: Add L2 assertions list endpoint**

```python
@memory_router.get("/l2/assertions")
async def list_l2_assertions(limit: int = Query(default=100, ge=1, le=500)):
    """List ToM trait assertions."""
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return []

    return await unified_memory.l2.list_tom_assertions(limit=limit)
```

- [ ] **Step 4: Commit backend L2 endpoints**

```bash
git add backend/src/magi/api/routers/memory.py
git commit -m "feat(api): add L2 cognition endpoints"
```

---

### Task 3: Add L3 Summaries Endpoint

**Files:**
- Modify: `backend/src/magi/api/routers/memory.py`

- [ ] **Step 1: Add L3 summaries list endpoint**

```python
@memory_router.get("/l3/summaries")
async def list_l3_summaries(
    limit: int = Query(default=100, ge=1, le=500),
    summary_type: Optional[str] = Query(default=None),
):
    """List L3 reflection summaries."""
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l3:
        return []

    return await unified_memory.l3.list_summaries(limit=limit)
```

- [ ] **Step 2: Commit backend L3 endpoint**

```bash
git add backend/src/magi/api/routers/memory.py
git commit -m "feat(api): add L3 summaries endpoint"
```

---

### Task 4: Update Statistics Endpoint

**Files:**
- Modify: `backend/src/magi/api/routers/memory.py`

- [ ] **Step 1: Update statistics endpoint to return new format**

Replace the existing `get_memory_statistics` function:

```python
@memory_router.get("/statistics")
async def get_memory_statistics():
    unified_memory = get_unified_memory()
    memory_integration = get_memory_integration()

    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    stats: Dict[str, Any] = {}

    # L0 statistics
    if unified_memory.l0:
        sessions = unified_memory.l0._sessions
        total_goals = sum(len(unified_memory.l0._goal_stack.get(sid, [])) for sid in sessions)
        total_entities = sum(len(unified_memory.l0._active_entities.get(sid, {})) for sid in sessions)
        total_tactics = sum(len(unified_memory.l0._temporary_tactics.get(sid, {})) for sid in sessions)
        stats["l0"] = {
            "active_sessions": len(sessions),
            "total_goals": total_goals,
            "total_entities": total_entities,
            "total_tactics": total_tactics,
        }
    else:
        stats["l0"] = {"active_sessions": 0, "total_goals": 0, "total_entities": 0, "total_tactics": 0}

    # L1 statistics
    if unified_memory.l1:
        stats["l1"] = {
            "event_count": await unified_memory.l1.count_events(),
            "db_path": unified_memory.l1.db_path,
        }
    else:
        stats["l1"] = {"event_count": 0, "db_path": None}

    # L2 statistics
    if unified_memory.l2:
        relations = await unified_memory.l2.get_relationships(limit=10000)
        assertions = await unified_memory.l2.list_tom_assertions(limit=10000)
        stats["l2"] = {
            "relation_count": len(relations),
            "assertion_count": len(assertions),
            "db_path": unified_memory.l2.db_path,
        }
    else:
        stats["l2"] = {"relation_count": 0, "assertion_count": 0, "db_path": None}

    # L3 statistics
    if unified_memory.l3:
        summaries = await unified_memory.l3.list_summaries(limit=10000)
        stats["l3"] = {
            "summary_count": len(summaries),
            "db_path": unified_memory.l3.db_path,
        }
    else:
        stats["l3"] = {"summary_count": 0, "db_path": None}

    # L4 statistics
    if unified_memory.l4:
        skills = await unified_memory.l4.get_all_skills(limit=10000)
        open_breakers = sum(1 for s in skills if s.get("circuit_breaker_state") != "closed")
        stats["l4"] = {
            "skill_count": len(skills),
            "open_circuit_breakers": open_breakers,
            "db_path": unified_memory.l4.db_path,
        }
    else:
        stats["l4"] = {"skill_count": 0, "open_circuit_breakers": 0, "db_path": None}

    if memory_integration:
        stats["integration"] = memory_integration.get_statistics()

    return stats
```

- [ ] **Step 2: Commit statistics update**

```bash
git add backend/src/magi/api/routers/memory.py
git commit -m "feat(api): update statistics endpoint for L0-L4 architecture"
```

---

## Chunk 2: Frontend API Module

### Task 5: Update Frontend API Module

**Files:**
- Modify: `frontend/src/api/modules/memory.ts`

- [ ] **Step 1: Update API interfaces and methods**

Replace the entire file content:

```typescript
import { api } from '../client';

export interface L0Session {
  session_id: string;
  user_id?: string;
  status: string;
  started_at: number;
  last_active_at: number;
  goal_count: number;
  entity_count: number;
  tactic_count: number;
}

export interface L0Stats {
  active_sessions: number;
  total_goals: number;
  total_entities: number;
  total_tactics: number;
}

export interface L0Workbench {
  session: Record<string, unknown> | null;
  goal_stack: Array<Record<string, unknown>>;
  active_entities: Array<Record<string, unknown>>;
  temporary_tactics: Array<Record<string, unknown>>;
}

export interface L1Event {
  event_id: string;
  event_type: string;
  raw_content: string;
  timestamp: number;
  source: string;
  memory_domain: string;
  retention_class: string;
  importance_score: number;
}

export interface L2Relation {
  triple_id: string;
  subject_id: string;
  subject_type: string;
  predicate: string;
  object_id: string;
  object_type: string;
  confidence: number;
  evidence_event_ids: string[];
  observation_count: number;
}

export interface L2Assertion {
  assertion_id: string;
  entity_id: string;
  entity_type: string;
  trait_name: string;
  trait_value: string;
  confidence_score: number;
  evidence_events: string[];
  validation_state: string;
}

export interface L3Summary {
  summary_id: string;
  summary_type: string;
  summary_category: string;
  period_start: number;
  period_end: number;
  content: string;
  source_event_count: number;
}

export interface L4Skill {
  skill_id: string;
  skill_name: string;
  skill_category: string;
  proficiency: number;
  success_rate: number;
  total_attempts: number;
  circuit_breaker_state: string;
}

export interface MemoryStatistics {
  l0: L0Stats;
  l1: { event_count: number; db_path?: string };
  l2: { relation_count: number; assertion_count: number; db_path?: string };
  l3: { summary_count: number; db_path?: string };
  l4: { skill_count: number; open_circuit_breakers: number; db_path?: string };
}

export interface ClearMemoryResult {
  cleared: boolean;
  count: number;
}

export interface ClearMemoryResponse {
  success: boolean;
  results: {
    l0: ClearMemoryResult;
    l1: ClearMemoryResult;
    l2: ClearMemoryResult;
    l3: ClearMemoryResult;
    l4: ClearMemoryResult;
    chat_context: ClearMemoryResult;
  };
  warnings?: string[];
}

export const memoryApi = {
  // L0 Working Memory
  getL0Sessions: () =>
    api.get<{ sessions: L0Session[]; stats: L0Stats }>('/memory/l0/sessions'),
  getL0Workbench: (sessionId: string) =>
    api.get<L0Workbench>(`/memory/l0/workbench/${sessionId}`),

  // L1 Event Stream
  getL1Events: (params?: { limit?: number; event_type?: string }) =>
    api.get<{ events: L1Event[]; stats: { total: number } }>('/memory/l1/events', { params }),

  // L2 Cognition
  getL2Statistics: () =>
    api.get<{ relation_count: number; assertion_count: number; db_path?: string }>('/memory/l2/statistics'),
  getL2Relations: (limit?: number) =>
    api.get<L2Relation[]>('/memory/l2/relations', { params: { limit } }),
  getL2Assertions: (limit?: number) =>
    api.get<L2Assertion[]>('/memory/l2/assertions', { params: { limit } }),

  // L3 Reflection
  getL3Summaries: (limit?: number) =>
    api.get<L3Summary[]>('/memory/l3/summaries', { params: { limit } }),

  // L4 Procedural
  getL4Skills: (limit?: number) =>
    api.get<L4Skill[]>('/memory/procedures', { params: { limit } }),

  // Statistics & Search
  getStatistics: () =>
    api.get<MemoryStatistics>('/memory/statistics'),
  search: (query: string, options?: { limit?: number; query_mode?: string }) =>
    api.post('/memory/search', { query, limit: options?.limit ?? 20, query_mode: options?.query_mode ?? 'detail' }),

  // Clear
  clearAll: () =>
    api.delete<ClearMemoryResponse>('/memory/clear') as unknown as Promise<ClearMemoryResponse>,
};

export default memoryApi;
```

- [ ] **Step 2: Commit frontend API update**

```bash
git add frontend/src/api/modules/memory.ts
git commit -m "feat(frontend): update memory API module for L0-L4 architecture"
```

---

## Chunk 3: Frontend Events.tsx Rewrite

### Task 6: Rewrite Events.tsx with New Architecture

**Files:**
- Modify: `frontend/src/pages/Events.tsx`

- [ ] **Step 1: Rewrite the entire Events.tsx file**

This is a complete rewrite. The new file structure:

```tsx
/**
 * Memory页面 - L0-L4 记忆系统
 */
import React, { useEffect, useState } from 'react';
import {
  AlertTriangle,
  Brain,
  Database,
  FileText,
  Network,
  RefreshCw,
  Search,
  Target,
  Trash2,
  Users,
  Zap,
} from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { memoryApi, L0Session, L0Workbench, L1Event, L2Relation, L2Assertion, L3Summary, L4Skill, MemoryStatistics } from '@/api/modules/memory';

const CONFIRM_WAIT_SECONDS = 3;

const EventsPage: React.FC = () => {
  const { t } = useTranslation('app');
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('l0');

  // Statistics
  const [stats, setStats] = useState<MemoryStatistics>({
    l0: { active_sessions: 0, total_goals: 0, total_entities: 0, total_tactics: 0 },
    l1: { event_count: 0 },
    l2: { relation_count: 0, assertion_count: 0 },
    l3: { summary_count: 0 },
    l4: { skill_count: 0, open_circuit_breakers: 0 },
  });

  // L0 data
  const [l0Sessions, setL0Sessions] = useState<L0Session[]>([]);
  const [l0Workbench, setL0Workbench] = useState<L0Workbench | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  // L1 data
  const [l1Events, setL1Events] = useState<L1Event[]>([]);

  // L2 data
  const [l2Relations, setL2Relations] = useState<L2Relation[]>([]);
  const [l2Assertions, setL2Assertions] = useState<L2Assertion[]>([]);
  const [l2SubTab, setL2SubTab] = useState<'relations' | 'assertions'>('relations');

  // L3 data
  const [l3Summaries, setL3Summaries] = useState<L3Summary[]>([]);

  // L4 data
  const [l4Skills, setL4Skills] = useState<L4Skill[]>([]);

  // Search
  const [searchKeyword, setSearchKeyword] = useState('');

  // Clear dialog
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [countdown, setCountdown] = useState(CONFIRM_WAIT_SECONDS);

  const fetchAllData = async () => {
    setLoading(true);
    try {
      const [statsRes, l0Res, l1Res, l2RelRes, l2AssRes, l3Res, l4Res] = await Promise.all([
        memoryApi.getStatistics(),
        memoryApi.getL0Sessions(),
        memoryApi.getL1Events({ limit: 50 }),
        memoryApi.getL2Relations(100),
        memoryApi.getL2Assertions(100),
        memoryApi.getL3Summaries(100),
        memoryApi.getL4Skills(100),
      ]);
      setStats(statsRes);
      setL0Sessions(l0Res.sessions);
      setL1Events(l1Res.events);
      setL2Relations(l2RelRes);
      setL2Assertions(l2AssRes);
      setL3Summaries(l3Res);
      setL4Skills(l4Res);
    } catch (error: any) {
      toast.error(t('memory.loadFailed', { message: error.message }));
    } finally {
      setLoading(false);
    }
  };

  const fetchWorkbench = async (sessionId: string) => {
    try {
      const workbench = await memoryApi.getL0Workbench(sessionId);
      setL0Workbench(workbench);
    } catch {
      setL0Workbench(null);
    }
  };

  useEffect(() => {
    fetchAllData();
  }, []);

  useEffect(() => {
    if (selectedSessionId) {
      fetchWorkbench(selectedSessionId);
    }
  }, [selectedSessionId]);

  useEffect(() => {
    if (!showClearConfirm) {
      setCountdown(CONFIRM_WAIT_SECONDS);
      return;
    }
    if (countdown <= 0) return;
    const timer = setTimeout(() => setCountdown((prev) => prev - 1), 1000);
    return () => clearTimeout(timer);
  }, [showClearConfirm, countdown]);

  const handleSearch = async () => {
    if (!searchKeyword.trim()) {
      toast.warning(t('memory.searchKeywordRequired'));
      return;
    }
    setLoading(true);
    try {
      await memoryApi.search(searchKeyword);
      toast.success(t('memory.searchComplete'));
    } catch (error: any) {
      toast.error(t('memory.searchFailed', { message: error.message }));
    } finally {
      setLoading(false);
    }
  };

  const handleClearMemory = async () => {
    setClearing(true);
    try {
      const response = await memoryApi.clearAll();
      if (response.success) {
        const totalCleared = Object.values(response.results).reduce(
          (sum: number, result: any) => sum + (result.cleared ? result.count : 0),
          0
        );
        toast.success(t('memory.memoryCleared', { count: totalCleared }));
        window.dispatchEvent(new CustomEvent('magi-memory-cleared'));
        await fetchAllData();
      }
    } catch (error: any) {
      toast.error(error?.message || t('memory.memoryClearFailed'));
    } finally {
      setClearing(false);
      setShowClearConfirm(false);
    }
  };

  const formatDate = (ts: number) => new Date(ts * 1000).toLocaleString();
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'text-green-600';
      case 'completed': return 'text-blue-600';
      case 'failed': return 'text-red-600';
      default: return 'text-gray-600';
    }
  };

  return (
    <div className="space-y-4 text-sm">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{t('memory.title')}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t('memory.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => setShowClearConfirm(true)} disabled={loading}>
            <Trash2 className="mr-2 h-4 w-4" />
            <span>{t('memory.clearMemory')}</span>
          </Button>
          <Button onClick={fetchAllData} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            {t('memory.refresh')}
          </Button>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid h-auto grid-cols-2 gap-1 md:grid-cols-5">
          <TabsTrigger value="l0"><Brain className="mr-1 h-4 w-4" />{t('memory.tabs.l0')} ({stats.l0.active_sessions})</TabsTrigger>
          <TabsTrigger value="l1"><Database className="mr-1 h-4 w-4" />{t('memory.tabs.l1')} ({stats.l1.event_count})</TabsTrigger>
          <TabsTrigger value="l2"><Network className="mr-1 h-4 w-4" />{t('memory.tabs.l2')} ({stats.l2.relation_count + stats.l2.assertion_count})</TabsTrigger>
          <TabsTrigger value="l3"><FileText className="mr-1 h-4 w-4" />{t('memory.tabs.l3')} ({stats.l3.summary_count})</TabsTrigger>
          <TabsTrigger value="l4"><Zap className="mr-1 h-4 w-4" />{t('memory.tabs.l4')} ({stats.l4.skill_count})</TabsTrigger>
        </TabsList>

        {/* L0 Working Memory */}
        <TabsContent value="l0" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('memory.l0.activeSessions')}</p><p className="mt-1 text-2xl font-semibold">{stats.l0.active_sessions}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('memory.l0.totalGoals')}</p><p className="mt-1 text-2xl font-semibold text-blue-600">{stats.l0.total_goals}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('memory.l0.totalEntities')}</p><p className="mt-1 text-2xl font-semibold text-purple-600">{stats.l0.total_entities}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('memory.l0.totalTactics')}</p><p className="mt-1 text-2xl font-semibold text-amber-600">{stats.l0.total_tactics}</p></CardContent></Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>{t('memory.l0.sessions')}</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {loading ? <LoadingSpinner /> : l0Sessions.length === 0 ? (
                  <p className="text-muted-foreground">{t('memory.l0.noSessions')}</p>
                ) : (
                  l0Sessions.map((session) => (
                    <details
                      key={session.session_id}
                      className="overflow-hidden rounded-xl border border-border/70 bg-card p-0"
                      onToggle={(e) => {
                        if ((e.target as HTMLDetailsElement).open) {
                          setSelectedSessionId(session.session_id);
                        }
                      }}
                    >
                      <summary className="flex w-full cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm transition-colors hover:bg-muted/35">
                        <span className="min-w-0 flex-1 truncate font-medium">{session.session_id.slice(0, 16)}...</span>
                        <Badge variant="outline" className={getStatusColor(session.status)}>{session.status}</Badge>
                        <span className="shrink-0 text-xs text-muted-foreground">{formatDate(session.last_active_at)}</span>
                      </summary>
                      {l0Workbench && (
                        <div className="border-t border-border/60 px-4 pb-4 pt-3">
                          <div className="mb-3">
                            <p className="font-medium">{t('memory.l0.goalStack')}</p>
                            <div className="mt-1 space-y-1">
                              {l0Workbench.goal_stack.map((goal: any) => (
                                <div key={goal.goal_id} className="flex items-center gap-2 rounded bg-muted/30 p-2">
                                  <Target className="h-4 w-4 text-blue-600" />
                                  <span className="flex-1 truncate">{goal.description}</span>
                                  <Badge variant="outline">{goal.status}</Badge>
                                </div>
                              ))}
                              {l0Workbench.goal_stack.length === 0 && <p className="text-xs text-muted-foreground">{t('memory.l0.noGoals')}</p>}
                            </div>
                          </div>
                          <div>
                            <p className="font-medium">{t('memory.l0.activeEntities')}</p>
                            <div className="mt-1 flex flex-wrap gap-1">
                              {l0Workbench.active_entities.map((entity: any) => (
                                <Badge key={`${entity.entity_id}-${entity.entity_type}`} variant="secondary">
                                  <Users className="mr-1 h-3 w-3" />
                                  {entity.entity_id}
                                </Badge>
                              ))}
                              {l0Workbench.active_entities.length === 0 && <p className="text-xs text-muted-foreground">{t('memory.l0.noEntities')}</p>}
                            </div>
                          </div>
                        </div>
                      )}
                    </details>
                  ))
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle>{t('memory.l0.about')}</CardTitle></CardHeader>
              <CardContent className="space-y-3 text-sm">
                <p>{t('memory.l0.aboutDesc')}</p>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">{t('memory.l0.sessionState')}</Badge>
                  <Badge variant="outline">{t('memory.l0.goalStack')}</Badge>
                  <Badge variant="outline">{t('memory.l0.activeEntities')}</Badge>
                  <Badge variant="outline">{t('memory.l0.temporaryTactics')}</Badge>
                </div>
                <p className="text-muted-foreground">{t('memory.l0.checkpointHint')}</p>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* L1 Event Stream */}
        <TabsContent value="l1" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('memory.l1.totalEvents')}</p><p className="mt-1 text-2xl font-semibold">{stats.l1.event_count}</p></CardContent></Card>
          </div>
          <Card>
            <CardHeader><CardTitle>{t('memory.l1.rawEvents')}</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {loading ? <LoadingSpinner /> : l1Events.map((event) => (
                <details key={event.event_id} className="overflow-hidden rounded-xl border border-border/70 bg-card p-0">
                  <summary className="flex w-full cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm transition-colors hover:bg-muted/35">
                    <span className="min-w-0 flex-1 truncate font-medium">{event.event_type}</span>
                    <Badge variant="outline">{event.memory_domain}</Badge>
                    <span className="shrink-0 text-xs text-muted-foreground">{formatDate(event.timestamp)}</span>
                  </summary>
                  <div className="grid gap-2 border-t border-border/60 px-4 pb-4 pt-3 text-xs">
                    <div>ID: {event.event_id}</div>
                    <div>{t('memory.l1.source')}: {event.source}</div>
                    <div>{t('memory.l1.retention')}: {event.retention_class}</div>
                    <div>{t('memory.l1.importance')}: {event.importance_score.toFixed(2)}</div>
                    <pre className="max-h-52 overflow-auto rounded bg-muted p-2">{event.raw_content}</pre>
                  </div>
                </details>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        {/* L2 Cognition */}
        <TabsContent value="l2" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('memory.l2.relations')}</p><p className="mt-1 text-2xl font-semibold">{stats.l2.relation_count}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('memory.l2.assertions')}</p><p className="mt-1 text-2xl font-semibold">{stats.l2.assertion_count}</p></CardContent></Card>
          </div>

          <Tabs value={l2SubTab} onValueChange={(v) => setL2SubTab(v as 'relations' | 'assertions')}>
            <TabsList>
              <TabsTrigger value="relations">{t('memory.l2.knowledgeGraph')}</TabsTrigger>
              <TabsTrigger value="assertions">{t('memory.l2.tomAssertions')}</TabsTrigger>
            </TabsList>

            <TabsContent value="relations" className="mt-4">
              <Card>
                <CardHeader><CardTitle>{t('memory.l2.relationsList')}</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {l2Relations.map((rel) => (
                    <div key={rel.triple_id} className="rounded-md border p-3">
                      <div className="flex items-center gap-2">
                        <Badge variant="secondary">{rel.subject_type}</Badge>
                        <span className="font-medium">{rel.subject_id}</span>
                        <span className="text-muted-foreground">→</span>
                        <Badge>{rel.predicate}</Badge>
                        <span className="text-muted-foreground">→</span>
                        <Badge variant="secondary">{rel.object_type}</Badge>
                        <span className="font-medium">{rel.object_id}</span>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {t('memory.l2.confidence')}: {(rel.confidence * 100).toFixed(0)}% | {t('memory.l2.observations')}: {rel.observation_count}
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="assertions" className="mt-4">
              <Card>
                <CardHeader><CardTitle>{t('memory.l2.assertionsList')}</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {l2Assertions.map((assertion) => (
                    <div key={assertion.assertion_id} className="rounded-md border p-3">
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{assertion.entity_id}</span>
                        <Badge variant={assertion.validation_state === 'stable' ? 'success' : assertion.validation_state === 'contradicted' ? 'destructive' : 'outline'}>
                          {assertion.validation_state}
                        </Badge>
                      </div>
                      <div className="mt-1 text-sm">
                        {assertion.trait_name}: <span className="font-medium">{assertion.trait_value}</span>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {t('memory.l2.confidence')}: {(assertion.confidence_score * 100).toFixed(0)}%
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </TabsContent>

        {/* L3 Reflection */}
        <TabsContent value="l3" className="space-y-4">
          <Card>
            <CardContent className="p-4">
              <p className="text-xs text-muted-foreground">{t('memory.l3.summaryCount')}</p>
              <p className="mt-1 text-2xl font-semibold">{stats.l3.summary_count}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>{t('memory.l3.summariesList')}</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {l3Summaries.map((summary) => (
                <details key={summary.summary_id} className="overflow-hidden rounded-xl border border-border/70 bg-card p-0">
                  <summary className="flex w-full cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm transition-colors hover:bg-muted/35">
                    <Badge variant="outline">{summary.summary_type}</Badge>
                    <Badge variant="secondary">{summary.summary_category}</Badge>
                    <span className="shrink-0 text-xs text-muted-foreground">{formatDate(summary.period_start)}</span>
                  </summary>
                  <div className="border-t border-border/60 px-4 pb-4 pt-3">
                    <p className="text-sm">{summary.content}</p>
                    <div className="mt-2 text-xs text-muted-foreground">
                      {t('memory.l3.sourceEvents')}: {summary.source_event_count}
                    </div>
                  </div>
                </details>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        {/* L4 Procedural */}
        <TabsContent value="l4" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('memory.l4.skillCount')}</p><p className="mt-1 text-2xl font-semibold">{stats.l4.skill_count}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('memory.l4.openBreakers')}</p><p className="mt-1 text-2xl font-semibold text-red-600">{stats.l4.open_circuit_breakers}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('memory.l4.highSuccess')}</p><p className="mt-1 text-2xl font-semibold text-green-600">{l4Skills.filter(s => s.success_rate > 0.8).length}</p></CardContent></Card>
          </div>
          <Card>
            <CardHeader><CardTitle>{t('memory.l4.skillsList')}</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {l4Skills.map((skill) => (
                <div key={skill.skill_id} className="rounded-md border p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{skill.skill_name}</span>
                    <div className="flex items-center gap-2">
                      <Badge variant={skill.circuit_breaker_state === 'closed' ? 'success' : 'destructive'}>
                        {skill.circuit_breaker_state}
                      </Badge>
                      <Badge variant={skill.success_rate > 0.7 ? 'success' : skill.success_rate > 0.5 ? 'warning' : 'destructive'}>
                        {(skill.success_rate * 100).toFixed(0)}%
                      </Badge>
                    </div>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {t('memory.l4.category')}: {skill.skill_category} | {t('memory.l4.attempts')}: {skill.total_attempts}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Clear Dialog */}
      <Dialog open={showClearConfirm} onOpenChange={(open) => !clearing && setShowClearConfirm(open)}>
        <DialogContent hideClose className="max-w-lg overflow-hidden border-destructive/30 p-0">
          <DialogHeader className="border-b border-border/60 px-6 py-5">
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" />
              {t('memory.clearConfirm.title')}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 px-6 py-5">
            <div className="rounded-2xl border border-destructive/35 bg-destructive/10 p-4 text-sm">
              <p className="font-medium text-destructive">{t('memory.clearConfirm.warning')}</p>
              <ul className="mt-2 list-inside list-disc space-y-1 text-destructive/80">
                <li>{t('memory.clearConfirm.l0')}</li>
                <li>{t('memory.clearConfirm.l1')}</li>
                <li>{t('memory.clearConfirm.l2')}</li>
                <li>{t('memory.clearConfirm.l3')}</li>
                <li>{t('memory.clearConfirm.l4')}</li>
                <li>{t('memory.clearConfirm.chatContext')}</li>
              </ul>
              <p className="mt-3 font-semibold text-destructive">{t('memory.clearConfirm.irreversible')}</p>
            </div>
          </div>
          <DialogFooter className="border-t border-border/60 px-6 py-5">
            <Button variant="outline" onClick={() => setShowClearConfirm(false)} disabled={clearing}>
              {t('memory.clearConfirm.cancel')}
            </Button>
            <Button variant="destructive" onClick={handleClearMemory} disabled={clearing || countdown > 0} className="min-w-[120px]">
              {clearing ? t('memory.clearConfirm.clearing') : countdown > 0 ? t('memory.clearConfirm.wait', { seconds: countdown }) : t('memory.clearConfirm.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default EventsPage;
```

- [ ] **Step 2: Commit Events.tsx rewrite**

```bash
git add frontend/src/pages/Events.tsx
git commit -m "feat(frontend): rewrite Events.tsx for L0-L4 memory architecture"
```

---

## Chunk 4: i18n Updates

### Task 7: Update English Translations

**Files:**
- Modify: `frontend/src/i18n/locales/en/app.json`

- [ ] **Step 1: Replace events section with memory section**

Find the `"events"` section (around line 717) and replace it with:

```json
"memory": {
  "title": "Memory Viewer",
  "subtitle": "L0-L4 Layered Memory System",
  "refresh": "Refresh",
  "loadFailed": "Failed to load data: {{message}}",
  "searchKeywordRequired": "Please enter a search keyword",
  "searchComplete": "Search completed",
  "searchFailed": "Search failed: {{message}}",
  "clearMemory": "Clear",
  "memoryCleared": "Cleared {{count}} memory items",
  "memoryClearFailed": "Failed to clear memory",
  "tabs": {
    "l0": "L0",
    "l1": "L1",
    "l2": "L2",
    "l3": "L3",
    "l4": "L4"
  },
  "l0": {
    "activeSessions": "Active Sessions",
    "totalGoals": "Total Goals",
    "totalEntities": "Total Entities",
    "totalTactics": "Total Tactics",
    "sessions": "Sessions",
    "noSessions": "No active sessions",
    "goalStack": "Goal Stack",
    "noGoals": "No goals in stack",
    "activeEntities": "Active Entities",
    "noEntities": "No active entities",
    "about": "About L0",
    "aboutDesc": "L0 Working Memory maintains session-local state including goal stacks, active entity cards, and temporary tactics.",
    "sessionState": "Session State",
    "temporaryTactics": "Temporary Tactics",
    "checkpointHint": "Checkpoints are saved periodically for crash recovery."
  },
  "l1": {
    "totalEvents": "Total Events",
    "rawEvents": "Event Stream (latest 50)",
    "source": "Source",
    "retention": "Retention",
    "importance": "Importance"
  },
  "l2": {
    "relations": "Knowledge Relations",
    "assertions": "ToM Assertions",
    "knowledgeGraph": "Knowledge Graph",
    "tomAssertions": "ToM Assertions",
    "relationsList": "Relations",
    "assertionsList": "Assertions",
    "confidence": "Confidence",
    "observations": "Observations"
  },
  "l3": {
    "summaryCount": "Summary Count",
    "summariesList": "Summaries",
    "sourceEvents": "Source events"
  },
  "l4": {
    "skillCount": "Skill Count",
    "openBreakers": "Open Circuit Breakers",
    "highSuccess": "High Success Skills",
    "skillsList": "Skills",
    "category": "Category",
    "attempts": "Attempts"
  },
  "clearConfirm": {
    "title": "Clear All Memory",
    "warning": "This will permanently delete:",
    "l0": "L0 working context (sessions, goals)",
    "l1": "L1 event stream",
    "l2": "L2 cognition (knowledge graph, ToM)",
    "l3": "L3 reflection summaries",
    "l4": "L4 procedural skills",
    "chatContext": "Chat context history",
    "irreversible": "This action cannot be undone!",
    "cancel": "Cancel",
    "confirm": "Confirm Clear",
    "clearing": "Clearing...",
    "wait": "Wait {{seconds}}s"
  }
}
```

- [ ] **Step 2: Update dashboard memory architecture value**

Find `"memoryArchitectureValue"` in the dashboard section and change from `"L1-L5 Five Layers"` to `"L0-L4 Lifecycle"`.

- [ ] **Step 3: Commit English translations**

```bash
git add frontend/src/i18n/locales/en/app.json
git commit -m "feat(i18n): update English translations for L0-L4 memory"
```

---

### Task 8: Update Chinese Translations

**Files:**
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`

- [ ] **Step 1: Replace events section with memory section (Chinese)**

```json
"memory": {
  "title": "记忆查看器",
  "subtitle": "L0-L4 分层记忆系统",
  "refresh": "刷新",
  "loadFailed": "加载数据失败：{{message}}",
  "searchKeywordRequired": "请输入搜索关键词",
  "searchComplete": "搜索完成",
  "searchFailed": "搜索失败：{{message}}",
  "clearMemory": "清空",
  "memoryCleared": "已清空 {{count}} 条记忆",
  "memoryClearFailed": "清空记忆失败",
  "tabs": {
    "l0": "L0",
    "l1": "L1",
    "l2": "L2",
    "l3": "L3",
    "l4": "L4"
  },
  "l0": {
    "activeSessions": "活跃会话",
    "totalGoals": "总目标数",
    "totalEntities": "总实体数",
    "totalTactics": "总策略数",
    "sessions": "会话列表",
    "noSessions": "无活跃会话",
    "goalStack": "目标栈",
    "noGoals": "目标栈为空",
    "activeEntities": "活跃实体",
    "noEntities": "无活跃实体",
    "about": "关于 L0",
    "aboutDesc": "L0 工作记忆维护会话级状态，包括目标栈、活跃实体卡片和临时策略。",
    "sessionState": "会话状态",
    "temporaryTactics": "临时策略",
    "checkpointHint": "检查点定期保存以支持崩溃恢复。"
  },
  "l1": {
    "totalEvents": "总事件数",
    "rawEvents": "事件流（最新 50 条）",
    "source": "来源",
    "retention": "保留策略",
    "importance": "重要性"
  },
  "l2": {
    "relations": "知识关系",
    "assertions": "ToM 断言",
    "knowledgeGraph": "知识图谱",
    "tomAssertions": "ToM 断言",
    "relationsList": "关系列表",
    "assertionsList": "断言列表",
    "confidence": "置信度",
    "observations": "观测次数"
  },
  "l3": {
    "summaryCount": "摘要数量",
    "summariesList": "摘要列表",
    "sourceEvents": "源事件数"
  },
  "l4": {
    "skillCount": "技能数量",
    "openBreakers": "熔断中的技能",
    "highSuccess": "高成功率技能",
    "skillsList": "技能列表",
    "category": "类别",
    "attempts": "尝试次数"
  },
  "clearConfirm": {
    "title": "清空所有记忆",
    "warning": "这将永久删除：",
    "l0": "L0 工作上下文（会话、目标）",
    "l1": "L1 事件流",
    "l2": "L2 认知（知识图谱、ToM 断言）",
    "l3": "L3 反思摘要",
    "l4": "L4 程序性技能",
    "chatContext": "聊天上下文历史",
    "irreversible": "此操作不可撤销！",
    "cancel": "取消",
    "confirm": "确认清空",
    "clearing": "清空中...",
    "wait": "等待 {{seconds}} 秒"
  }
}
```

- [ ] **Step 2: Update dashboard memory architecture value in Chinese**

Change `"L1-L5 Five Layers"` to `"L0-L4 生命周期"`.

- [ ] **Step 3: Commit Chinese translations**

```bash
git add frontend/src/i18n/locales/zh-CN/app.json
git commit -m "feat(i18n): update Chinese translations for L0-L4 memory"
```

---

## Chunk 5: Final Verification

### Task 9: Manual Testing

- [ ] **Step 1: Start the backend server**

```bash
cd /Users/asuka/code/magi/backend && python -m uvicorn magi.main:app --reload
```

- [ ] **Step 2: Start the frontend dev server**

```bash
cd /Users/asuka/code/magi/frontend && npm run dev
```

- [ ] **Step 3: Verify each tab**

1. Open http://localhost:5173/memory
2. Check L0 tab displays session stats (may show 0 sessions initially)
3. Check L1 tab displays events with correct filters
4. Check L2 tab displays relations and assertions
5. Check L3 tab displays summaries
6. Check L4 tab displays skills with circuit breaker status
7. Verify statistics numbers are correct
8. Test clear memory dialog shows new L0-L4 warnings

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete memory page redesign for L0-L4 architecture"
```
