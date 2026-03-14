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
  Target,
  Trash2,
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
  L0Workbench,
  L1Event,
  L2Relation,
  L2Assertion,
  L3Summary,
  L4Skill,
  MemoryStatistics,
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

  // L3 data
  const [l3Summaries, setL3Summaries] = useState<L3Summary[]>([]);

  // L4 data
  const [l4Skills, setL4Skills] = useState<L4Skill[]>([]);

  // Clear dialog state
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const [clearConfirmText, setClearConfirmText] = useState('');
  const [clearing, setClearing] = useState(false);
  // const [clearCountdown, setClearCountdown] = useState(0);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searching, setSearching] = useState(false);

  // Load all statistics
  const loadStatistics = async () => {
    try {
      const data = await memoryApi.getStatistics();
      setStats(data);
    } catch (error) {
      console.error('Failed to load statistics:', error);
    }
  };

  // Load L0 sessions
  const loadL0Sessions = async () => {
    try {
      const data = await memoryApi.getL0Sessions();
      setL0Sessions(data.sessions || []);
    } catch (error) {
      console.error('Failed to load L0 sessions:', error);
    }
  };

  // Load L0 workbench for selected session
  const loadL0Workbench = async (sessionId: string) => {
    try {
      const data = await memoryApi.getL0Workbench(sessionId);
      setL0Workbench(data);
    } catch (error) {
      console.error('Failed to load L0 workbench:', error);
      setL0Workbench(null);
    }
  };

  // Load L1 events
  const loadL1Events = async () => {
    try {
      const data = await memoryApi.getL1Events({ limit: 100 });
      setL1Events(data.events || []);
    } catch (error) {
      console.error('Failed to load L1 events:', error);
    }
  };

  // Load L2 relations and assertions
  const loadL2Data = async () => {
    try {
      const [relations, assertions] = await Promise.all([
        memoryApi.getL2Relations(100),
        memoryApi.getL2Assertions(100),
      ]);
      setL2Relations(relations);
      setL2Assertions(assertions);
    } catch (error) {
      console.error('Failed to load L2 data:', error);
    }
  };

  // Load L3 summaries
  const loadL3Summaries = async () => {
    try {
      const data = await memoryApi.getL3Summaries({ limit: 100 });
      setL3Summaries(data);
    } catch (error) {
      console.error('Failed to load L3 summaries:', error);
    }
  };

  // Load L4 skills
  const loadL4Skills = async () => {
    try {
      const data = await memoryApi.getL4Skills(100);
      setL4Skills(data);
    } catch (error) {
      console.error('Failed to load L4 skills:', error);
    }
  };

  // Initial load
  useEffect(() => {
    const loadAll = async () => {
      setLoading(true);
      await Promise.all([
        loadStatistics(),
        loadL0Sessions(),
        loadL1Events(),
        loadL2Data(),
        loadL3Summaries(),
        loadL4Skills(),
      ]);
      setLoading(false);
    };
    loadAll();
  }, []);

  // Load workbench when session is selected
  useEffect(() => {
    if (selectedSessionId) {
      loadL0Workbench(selectedSessionId);
    }
  }, [selectedSessionId]);

  // Refresh current tab
  const handleRefresh = async () => {
    setLoading(true);
    await loadStatistics();
    switch (activeTab) {
      case 'l0':
        await loadL0Sessions();
        if (selectedSessionId) {
          await loadL0Workbench(selectedSessionId);
        }
        break;
      case 'l1':
        await loadL1Events();
        break;
      case 'l2':
        await loadL2Data();
        break;
      case 'l3':
        await loadL3Summaries();
        break;
      case 'l4':
        await loadL4Skills();
        break;
    }
    setLoading(false);
    toast.success(t('memory.refreshSuccess'));
  };

  // Search handler
  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const results = await memoryApi.search(searchQuery);
      toast.success(t('memory.searchComplete'));
      console.log('Search results:', results);
    } catch (error) {
      toast.error(t('memory.searchError', { message: String(error) }));
    } finally {
      setSearching(false);
    }
  };

  // Clear memory handlers
  const handleClearRequest = () => {
    setClearDialogOpen(true);
    setClearConfirmText('');
    setClearCountdown(CONFIRM_WAIT_SECONDS);
  };

  const handleClearConfirm = async () => {
    if (clearConfirmText !== 'CLEAR') return;
    setClearing(true);
    try {
      const result = await memoryApi.clearAll();
      toast.success(`Cleared ${result.results?.l0?.count || 0} items`);
      setClearDialogOpen(false);
      await handleRefresh();
    } catch (error) {
      toast.error(`Clear failed: ${error}`);
    } finally {
      setClearing(false);
    }
  };

  // Format timestamp
  const formatTime = (ts: number) => {
    if (!ts) return '-';
    return new Date(ts * 1000).toLocaleString();
  };

  // Render L0 Tab
  const renderL0Tab = () => (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.l0.active_sessions}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l0.activeSessions')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.l0.total_goals}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l0.totalGoals')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.l0.total_entities}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l0.totalEntities')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.l0.total_tactics}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l0.totalTactics')}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Target className="h-5 w-5" />
            {t('memory.l0.sessions')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {l0Sessions.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l0.noSessions')}
            </div>
          ) : (
            <div className="space-y-2">
              {l0Sessions.map((session) => (
                <div
                  key={session.session_id}
                  className={`p-3 border rounded-lg cursor-pointer hover:bg-accent ${
                    selectedSessionId === session.session_id ? 'bg-accent' : ''
                  }`}
                  onClick={() => setSelectedSessionId(session.session_id)}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm">{session.session_id.slice(0, 8)}</span>
                    <Badge variant={session.status === 'active' ? 'default' : 'secondary'}>
                      {session.status}
                    </Badge>
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    Goals: {session.goal_count} | Entities: {session.entity_count} | Tactics: {session.tactic_count}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {l0Workbench && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              {t('memory.l0.workbench')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div>
                <h4 className="font-medium mb-2">{t('memory.l0.goalStack')}</h4>
                {l0Workbench.goal_stack?.length > 0 ? (
                  <div className="space-y-1">
                    {l0Workbench.goal_stack.map((goal: Record<string, unknown>, i: number) => (
                      <div key={i} className="p-2 bg-muted rounded text-sm">
                        {String(goal.description || goal.goal_id || 'Goal')}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">{t('memory.l0.noGoals')}</div>
                )}
              </div>
              <div>
                <h4 className="font-medium mb-2">{t('memory.l0.activeEntities')}</h4>
                {Object.keys(l0Workbench.active_entities || {}).length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(l0Workbench.active_entities).map(([id, entity]: [string, unknown]) => (
                      <Badge key={id} variant="outline">
                        {String((entity as Record<string, unknown>)?.name || id)}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">{t('memory.l0.noEntities')}</div>
                )}
              </div>
              <div>
                <h4 className="font-medium mb-2">{t('memory.l0.tactics')}</h4>
                {Object.keys(l0Workbench.temporary_tactics || {}).length > 0 ? (
                  <div className="space-y-1">
                    {Object.entries(l0Workbench.temporary_tactics).map(([id, tactic]: [string, unknown]) => (
                      <div key={id} className="p-2 bg-muted rounded text-sm">
                        {String((tactic as Record<string, unknown>)?.name || id)}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">{t('memory.l0.noTactics')}</div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );

  // Render L1 Tab
  const renderL1Tab = () => (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.l1.event_count}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l1.totalEvents')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">
              {l1Events.filter(e => e.source === 'user').length}
            </div>
            <div className="text-sm text-muted-foreground">{t('memory.l1.userAuthored')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">
              {l1Events.filter(e => e.source !== 'user').length}
            </div>
            <div className="text-sm text-muted-foreground">{t('memory.l1.interaction')}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            {t('memory.l1.events')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {l1Events.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l1.noEvents')}
            </div>
          ) : (
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {l1Events.map((event) => (
                <div key={event.event_id} className="p-3 border rounded-lg">
                  <div className="flex items-center justify-between mb-1">
                    <Badge variant="outline">{event.event_type}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {formatTime(event.timestamp)}
                    </span>
                  </div>
                  <div className="text-sm truncate">{event.raw_content}</div>
                  <div className="flex gap-2 mt-2">
                    <Badge variant="secondary" className="text-xs">{event.source}</Badge>
                    <Badge variant="secondary" className="text-xs">{event.memory_domain}</Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );

  // Render L2 Tab
  const renderL2Tab = () => (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.l2.relation_count}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l2.relationCount')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.l2.assertion_count}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l2.assertionCount')}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Network className="h-5 w-5" />
            {t('memory.l2.relations')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {l2Relations.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l2.noRelations')}
            </div>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {l2Relations.slice(0, 50).map((rel) => (
                <div key={rel.triple_id} className="p-2 border rounded text-sm">
                  <span className="font-medium">{rel.subject_id}</span>
                  <span className="text-blue-500 mx-2">→ {rel.predicate} →</span>
                  <span className="font-medium">{rel.object_id}</span>
                  <Badge variant="secondary" className="ml-2 text-xs">
                    {(rel.confidence * 100).toFixed(0)}%
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Brain className="h-5 w-5" />
            {t('memory.l2.assertions')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {l2Assertions.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l2.noAssertions')}
            </div>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {l2Assertions.slice(0, 50).map((assertion) => (
                <div key={assertion.assertion_id} className="p-2 border rounded text-sm">
                  <div className="flex items-center justify-between">
                    <span>
                      <Badge variant="outline" className="mr-2">{assertion.entity_type}</Badge>
                      {assertion.entity_id}
                    </span>
                    <Badge variant="secondary" className="text-xs">
                      {(assertion.confidence_score * 100).toFixed(0)}%
                    </Badge>
                  </div>
                  <div className="text-muted-foreground mt-1">
                    {assertion.trait_name}: {assertion.trait_value}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );

  // Render L3 Tab
  const renderL3Tab = () => (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-4">
          <div className="text-2xl font-bold">{stats.l3.summary_count}</div>
          <div className="text-sm text-muted-foreground">{t('memory.l3.summaryCount')}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            {t('memory.l3.summaries')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {l3Summaries.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l3.noSummaries')}
            </div>
          ) : (
            <div className="space-y-4 max-h-96 overflow-y-auto">
              {l3Summaries.map((summary) => (
                <div key={summary.summary_id} className="p-4 border rounded-lg">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Badge>{summary.summary_type}</Badge>
                      <Badge variant="outline">{summary.summary_category}</Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {formatTime(summary.created_at)}
                    </span>
                  </div>
                  <p className="text-sm">{summary.content}</p>
                  {summary.key_topics?.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {summary.key_topics.map((topic, i) => (
                        <Badge key={i} variant="secondary" className="text-xs">{topic}</Badge>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );

  // Render L4 Tab
  const renderL4Tab = () => (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.l4.skill_count}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l4.skillCount')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold text-orange-500">
              {stats.l4.open_circuit_breakers}
            </div>
            <div className="text-sm text-muted-foreground">{t('memory.l4.openBreakers')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold text-green-500">
              {l4Skills.filter(s => s.success_rate > 0.8).length}
            </div>
            <div className="text-sm text-muted-foreground">{t('memory.l4.highSuccess')}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-5 w-5" />
            {t('memory.l4.skills')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {l4Skills.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l4.noSkills')}
            </div>
          ) : (
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {l4Skills.map((skill) => (
                <div key={skill.skill_id} className="p-3 border rounded-lg">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{skill.skill_name}</span>
                      <Badge variant="outline">{skill.skill_category}</Badge>
                    </div>
                    <Badge
                      variant={skill.circuit_breaker_state === 'closed' ? 'default' : 'destructive'}
                    >
                      {skill.circuit_breaker_state}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-4 text-sm text-muted-foreground">
                    <span>Success: {(skill.success_rate * 100).toFixed(1)}%</span>
                    <span>Attempts: {skill.total_attempts}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{t('memory.title')}</h1>
          <p className="text-muted-foreground">{t('memory.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            {t('memory.refresh')}
          </Button>
          <Button variant="destructive" size="sm" onClick={handleClearRequest}>
            <Trash2 className="h-4 w-4 mr-2" />
            {t('memory.clear')}
          </Button>
        </div>
      </div>

      {/* Search */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex gap-2">
            <input
              type="text"
              className="flex-1 px-3 py-2 border rounded-md"
              placeholder={t('memory.searchPlaceholder')}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
            <Button onClick={handleSearch} disabled={searching}>
              {searching ? <LoadingSpinner /> : t('memory.search')}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid grid-cols-5 w-full">
          <TabsTrigger value="l0">L0</TabsTrigger>
          <TabsTrigger value="l1">L1</TabsTrigger>
          <TabsTrigger value="l2">L2</TabsTrigger>
          <TabsTrigger value="l3">L3</TabsTrigger>
          <TabsTrigger value="l4">L4</TabsTrigger>
        </TabsList>

        <TabsContent value="l0" className="mt-4">
          {loading ? <LoadingSpinner /> : renderL0Tab()}
        </TabsContent>
        <TabsContent value="l1" className="mt-4">
          {loading ? <LoadingSpinner /> : renderL1Tab()}
        </TabsContent>
        <TabsContent value="l2" className="mt-4">
          {loading ? <LoadingSpinner /> : renderL2Tab()}
        </TabsContent>
        <TabsContent value="l3" className="mt-4">
          {loading ? <LoadingSpinner /> : renderL3Tab()}
        </TabsContent>
        <TabsContent value="l4" className="mt-4">
          {loading ? <LoadingSpinner /> : renderL4Tab()}
        </TabsContent>
      </Tabs>

      {/* Architecture Info */}
      <Card>
        <CardContent className="pt-4">
          <div className="text-sm text-muted-foreground">
            {t('memory.architectureLabel')}: <strong>{t('memory.memoryArchitectureValue')}</strong>
          </div>
        </CardContent>
      </Card>

      {/* Clear Dialog */}
      <Dialog open={clearDialogOpen} onOpenChange={setClearDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              {t('memory.clearConfirm.title')}
            </DialogTitle>
            <DialogDescription>
              {t('memory.clearConfirm.description')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <ul className="text-sm space-y-1">
              <li>{t('memory.clearConfirm.l0')}</li>
              <li>{t('memory.clearConfirm.l1')}</li>
              <li>{t('memory.clearConfirm.l2')}</li>
              <li>{t('memory.clearConfirm.l3')}</li>
              <li>{t('memory.clearConfirm.l4')}</li>
              <li>{t('memory.clearConfirm.chatContext')}</li>
            </ul>
            <div>
              <label className="text-sm font-medium">
                {t('memory.clearConfirm.typePrompt')}
              </label>
              <input
                type="text"
                className="w-full mt-1 px-3 py-2 border rounded-md"
                value={clearConfirmText}
                onChange={(e) => setClearConfirmText(e.target.value)}
                placeholder="CLEAR"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setClearDialogOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={handleClearConfirm}
              disabled={clearConfirmText !== 'CLEAR' || clearing}
            >
              {clearing ? <LoadingSpinner /> : t('memory.clearConfirm.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default EventsPage;
