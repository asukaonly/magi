/**
 * Memory页面 - L0-L4 记忆系统
 */
import React, { useEffect, useState } from 'react';
import {
  AlertTriangle,
  Brain
  Database
  FileText
  Network
  RefreshCw
  Target,
  Trash2
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
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { memoryApi } from '@/api/modules/memory';
import type {
  L0Session,
  L0Workbench
  L1Event
  L2Relation
  L2Assertion
  L3Summary
  L4Skill
  MemoryStatistics
} from '@/api/modules/memory';

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
        memoryApi.getL3Summaries({ limit: 100 }),
        memoryApi.getL4Skills(100),
      ]);
      setStats(statsRes);
      setL0Sessions(l0Res.sessions || []);
      setL1Events(l1Res.events || []);
      setL2Relations(l2RelRes || []);
      setL2Assertions(l2AssRes || []);
      setL3Summaries(l3Res || []);
      setL4Skills(l4Res || []);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      toast.error(t('memory.loadFailed', { message }));
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

  const handleClearMemory = async () => {
    setClearing(true);
    try {
      const response = await memoryApi.clearAll();
      if (response.success) {
        const totalCleared = Object.values(response.results).reduce(
          (sum: number, result: { cleared: boolean; count: number }) => sum + (result.cleared ? result.count : 0),
          0
        );
        toast.success(t('memory.memoryCleared', { count: totalCleared }));
        window.dispatchEvent(new CustomEvent('magi-memory-cleared'));
        await fetchAllData();
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      toast.error(message || t('memory.memoryClearFailed'));
    } finally {
      setClearing(false);
      setShowClearConfirm(false);
    }
  };

  const formatDate = (ts: number) => new Date(ts * 1000).toLocaleString();
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active':
        return 'text-green-600';
      case 'completed':
        return 'text-blue-600';
      case 'failed':
        return 'text-red-600';
      default:
        return 'text-gray-600';
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
          <TabsTrigger value="l0">
            <Brain className="mr-1 h-4 w-4" />
            {t('memory.tabs.l0')} ({stats.l0.active_sessions})
          </TabsTrigger>
          <TabsTrigger value="l1">
            <Database className="mr-1 h-4 w-4" />
            {t('memory.tabs.l1')} ({stats.l1.event_count})
          </TabsTrigger>
          <TabsTrigger value="l2">
            <Network className="mr-1 h-4 w-4" />
            {t('memory.tabs.l2')} ({stats.l2.relation_count + stats.l2.assertion_count})
          </TabsTrigger>
          <TabsTrigger value="l3">
            <FileText className="mr-1 h-4 w-4" />
            {t('memory.tabs.l3')} ({stats.l3.summary_count})
          </TabsTrigger>
          <TabsTrigger value="l4">
            <Zap className="mr-1 h-4 w-4" />
            {t('memory.tabs.l4')} ({stats.l4.skill_count})
          </TabsTrigger>
        </TabsList>

        {/* L0 Working Memory */}
        <TabsContent value="l0" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-muted-foreground">{t('memory.l0.activeSessions')}</p>
                <p className="mt-1 text-2xl font-semibold">{stats.l0.active_sessions}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-muted-foreground">{t('memory.l0.totalGoals')}</p>
                <p className="mt-1 text-2xl font-semibold text-blue-600">{stats.l0.total_goals}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-muted-foreground">{t('memory.l0.totalEntities')}</p>
                <p className="mt-1 text-2xl font-semibold text-purple-600">{stats.l0.total_entities}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-muted-foreground">{t('memory.l0.totalTactics')}</p>
                <p className="mt-1 text-2xl font-semibold text-amber-600">{stats.l0.total_tactics}</p>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>{t('memory.l0.sessions')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {loading ? (
                  <LoadingSpinner />
                ) : l0Sessions.length === 0 ? (
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
                        <span className="min-w-0 flex-1 truncate font-medium">
                          {session.session_id.slice(0, 16)}...
                        </span>
                        <Badge variant="outline" className={getStatusColor(session.status)}>
                          {session.status}
                        </Badge>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {formatDate(session.last_active_at)}
                        </span>
                      </summary>
                      {l0Workbench && (
                        <div className="border-t border-border/60 px-4 pb-4 pt-3">
                          <div className="mb-3">
                            <p className="font-medium">{t('memory.l0.goalStack')}</p>
                            <div className="mt-1 space-y-1">
                              {(l0Workbench.goal_stack as Array<{ goal_id: string; description: string; status: string }>).map((goal) => (
                                <div key={goal.goal_id} className="flex items-center gap-2 rounded bg-muted/30 p-2">
                                  <Target className="h-4 w-4 text-blue-600" />
                                  <span className="flex-1 truncate">{goal.description}</span>
                                  <Badge variant="outline">{goal.status}</Badge>
                                </div>
                              ))}
                              {l0Workbench.goal_stack.length === 0 && (
                                <p className="text-xs text-muted-foreground">{t('memory.l0.noGoals')}</p>
                              )}
                            </div>
                          </div>
                          <div>
                            <p className="font-medium">{t('memory.l0.activeEntities')}</p>
                            <div className="mt-1 flex flex-wrap gap-1">
                              {(l0Workbench.active_entities as Array<{ entity_id: string; entity_type: string }>).map((entity) => (
                                <Badge key={`${entity.entity_id}-${entity.entity_type}`} variant="secondary">
                                  <Users className="mr-1 h-3 w-3" />
                                  {entity.entity_id}
                                </Badge>
                              ))}
                              {l0Workbench.active_entities.length === 0 && (
                                <p className="text-xs text-muted-foreground">{t('memory.l0.noEntities')}</p>
                              )}
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
              <CardHeader>
                <CardTitle>{t('memory.l0.about')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
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
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-muted-foreground">{t('memory.l1.totalEvents')}</p>
                <p className="mt-1 text-2xl font-semibold">{stats.l1.event_count}</p>
              </CardContent>
            </Card>
          </div>
          <Card>
            <CardHeader>
              <CardTitle>{t('memory.l1.rawEvents')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {loading ? (
                <LoadingSpinner />
              ) : (
                l1Events.map((event) => (
                  <details
                    key={event.event_id}
                    className="overflow-hidden rounded-xl border border-border/70 bg-card p-0"
                  >
                    <summary className="flex w-full cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm transition-colors hover:bg-muted/35">
                      <span className="min-w-0 flex-1 truncate font-medium">{event.event_type}</span>
                      <Badge variant="outline">{event.memory_domain}</Badge>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {formatDate(event.timestamp)}
                      </span>
                    </summary>
                    <div className="grid gap-2 border-t border-border/60 px-4 pb-4 pt-3 text-xs">
                      <div>ID: {event.event_id}</div>
                      <div>{t('memory.l1.source')}: {event.source}</div>
                      <div>{t('memory.l1.retention')}: {event.retention_class}</div>
                      <div>{t('memory.l1.importance')}: {event.importance_score.toFixed(2)}</div>
                      <pre className="max-h-52 overflow-auto rounded bg-muted p-2">{event.raw_content}</pre>
                    </div>
                  </details>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* L2 Cognition */}
        <TabsContent value="l2" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-muted-foreground">{t('memory.l2.relations')}</p>
                <p className="mt-1 text-2xl font-semibold">{stats.l2.relation_count}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-muted-foreground">{t('memory.l2.assertions')}</p>
                <p className="mt-1 text-2xl font-semibold">{stats.l2.assertion_count}</p>
              </CardContent>
            </Card>
          </div>

          <Tabs value={l2SubTab} onValueChange={(v) => setL2SubTab(v as 'relations' | 'assertions')}>
            <TabsList>
              <TabsTrigger value="relations">{t('memory.l2.knowledgeGraph')}</TabsTrigger>
              <TabsTrigger value="assertions">{t('memory.l2.tomAssertions')}</TabsTrigger>
            </TabsList>

            <TabsContent value="relations" className="mt-4">
              <Card>
                <CardHeader>
                  <CardTitle>{t('memory.l2.relationsList')}</CardTitle>
                </CardHeader>
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
                  {l2Relations.length === 0 && (
                    <p className="text-muted-foreground">{t('memory.l2.noRelations')}</p>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="assertions" className="mt-4">
              <Card>
                <CardHeader>
                  <CardTitle>{t('memory.l2.assertionsList')}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {l2Assertions.map((assertion) => (
                    <div key={assertion.assertion_id} className="rounded-md border p-3">
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{assertion.entity_id}</span>
                        <Badge
                          variant={
                            assertion.validation_state === 'stable'
                              ? 'success'
                              : assertion.validation_state === 'contradicted'
                                ? 'destructive'
                                : 'outline'
                          }
                        >
                          {assertion.validation_state}
                        </Badge>
                      </div>
                      <div className="mt-1 text-sm">
                        {assertion.trait_name}: <span className="font-medium">{assertion.trait_value}</span>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {t('memory.l2.confidence')}: {(assertion.confidence_score * 100).toFixed(1)}%
                      </div>
                    </div>
                  ))}
                  {l2Assertions.length === 0 && (
                    <p className="text-muted-foreground">{t('memory.l2.noAssertions')}</p>
                  )}
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
            <CardHeader>
              <CardTitle>{t('memory.l3.summariesList')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {l3Summaries.map((summary) => (
                <details
                  key={summary.summary_id}
                  className="overflow-hidden rounded-xl border border-border/70 bg-card p-0"
                >
                  <summary className="flex w-full cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm transition-colors hover:bg-muted/35">
                    <Badge variant="outline">{summary.summary_type}</Badge>
                    <Badge variant="secondary">{summary.summary_category}</Badge>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {formatDate(summary.period_start)}
                    </span>
                  </summary>
                  <div className="border-t border-border/60 px-4 pb-4 pt-3">
                    <p className="text-sm">{summary.content}</p>
                    <div className="mt-2 text-xs text-muted-foreground">
                      {t('memory.l3.sourceEvents')}: {summary.source_event_count}
                    </div>
                  </div>
                </details>
              ))}
              {l3Summaries.length === 0 && (
                <p className="text-muted-foreground">{t('memory.l3.noSummaries')}</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* L4 Procedural */}
        <TabsContent value="l4" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-muted-foreground">{t('memory.l4.skillCount')}</p>
                <p className="mt-1 text-2xl font-semibold">{stats.l4.skill_count}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-muted-foreground">{t('memory.l4.openBreakers')}</p>
                <p className="mt-1 text-2xl font-semibold text-red-600">{stats.l4.open_circuit_breakers}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-muted-foreground">{t('memory.l4.highSuccess')}</p>
                <p className="mt-1 text-2xl font-semibold text-green-600">
                  {l4Skills.filter((s) => s.success_rate > 0.8).length}
                </p>
              </CardContent>
            </Card>
          </div>
          <Card>
            <CardHeader>
              <CardTitle>{t('memory.l4.skillsList')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {l4Skills.map((skill) => (
                <div key={skill.skill_id} className="rounded-md border p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{skill.skill_name}</span>
                    <div className="flex items-center gap-2">
                      <Badge
                        variant={
                          skill.circuit_breaker_state === 'closed' ? 'success' : 'destructive'
                        }
                      >
                        {skill.circuit_breaker_state}
                      </Badge>
                      <Badge
                        variant={
                          skill.success_rate > 0.7
                            ? 'success'
                            : skill.success_rate > 0.5
                              ? 'secondary'
                              : 'destructive'
                        }
                      >
                        {(skill.success_rate * 100).toFixed(0)}%
                      </Badge>
                    </div>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {t('memory.l4.category')}: {skill.skill_category} | {t('memory.l4.attempts')}: {skill.total_attempts}
                  </div>
                </div>
              ))}
              {l4Skills.length === 0 && (
                <p className="text-muted-foreground">{t('memory.l4.noSkills')}</p>
              )}
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
            <DialogDescription className="sr-only">{t('memory.clearConfirm.warning')}</DialogDescription>
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
            <Button
              variant="destructive"
              onClick={handleClearMemory}
              disabled={clearing || countdown > 0}
              className="min-w-[120px]"
            >
              {clearing
                ? t('memory.clearConfirm.clearing')
                : countdown > 0
                  ? t('memory.clearConfirm.wait', { seconds: countdown })
                  : t('memory.clearConfirm.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default EventsPage;
