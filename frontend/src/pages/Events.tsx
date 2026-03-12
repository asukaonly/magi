/**
 * Events页面 - L1-L5 记忆查看
 */
import React, { useEffect, useState } from 'react';
import {
  Database,
  FileText,
  GitBranch,
  Network,
  RefreshCw,
  Search,
  Zap,
} from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { apiClient } from '../api/client';

interface Event {
  id: string;
  type: string;
  data: any;
  timestamp: number;
  source: string;
  level: number;
  correlation_id: string;
  metadata: any;
}

interface SearchResult {
  event_id: string;
  text: string;
  metadata: any;
}

interface Capability {
  capability_id: string;
  name: string;
  description: string;
  success_rate: number;
  usage_count: number;
}

const EventsPage: React.FC = () => {
  const { t } = useTranslation('app');
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('l1');

  // L1 数据
  const [l1Events, setL1Events] = useState<Event[]>([]);
  const [l1Stats, setL1Stats] = useState({ total: 0 });

  // L2 数据
  const [l2Stats, setL2Stats] = useState({ total_events: 0, total_relations: 0 });

  // L3 数据
  const [l3Results, setL3Results] = useState<SearchResult[]>([]);
  const [l3Stats, setL3Stats] = useState({ total_embeddings: 0, dimension: 0 });

  // L4 数据
  const [l4Stats, setL4Stats] = useState({ total_summaries: 0 });

  // L5 数据
  const [l5Capabilities, setL5Capabilities] = useState<Capability[]>([]);
  const [l5Stats, setL5Stats] = useState({ total_capabilities: 0 });

  // 搜索关键词
  const [searchKeyword, setSearchKeyword] = useState('');

  const fetchAllData = async () => {
    setLoading(true);
    try {
      await Promise.all([
        fetchL1Data(),
        fetchL2Data(),
        fetchL3Data(),
        fetchL4Data(),
        fetchL5Data(),
      ]);
    } catch (error: any) {
      toast.error(t('events.loadFailed', { message: error.message }));
    } finally {
      setLoading(false);
    }
  };

  // L1: 获取原始事件
  const fetchL1Data = async () => {
    try {
      const response = await apiClient.get('/memory/l1/events', { params: { limit: 50 } });
      setL1Events(response.data.events || []);
      setL1Stats(response.data.stats || { total: 0 });
    } catch (error) {
      console.error('Failed to fetch L1 data:', error);
      setL1Events([]);
      setL1Stats({ total: 0 });
    }
  };

  // L2: 获取事件关系
  const fetchL2Data = async () => {
    try {
      const response = await apiClient.get('/memory/l2/statistics');
      setL2Stats(response.data || { total_events: 0, total_relations: 0 });
    } catch (error) {
      console.error('Failed to fetch L2 data:', error);
    }
  };

  // L3: 获取嵌入向量
  const fetchL3Data = async () => {
    try {
      const response = await apiClient.get('/memory/statistics');
      const stats = response.data.l3_embeddings || {};
      setL3Stats(stats);
    } catch (error) {
      console.error('Failed to fetch L3 data:', error);
    }
  };

  // L4: 获取摘要
  const fetchL4Data = async () => {
    try {
      const response = await apiClient.get('/memory/statistics');
      const stats = response.data.l4_summaries || {};
      setL4Stats(stats);
    } catch (error) {
      console.error('Failed to fetch L4 data:', error);
    }
  };

  // L5: 获取能力
  const fetchL5Data = async () => {
    try {
      const response = await apiClient.get('/memory/capabilities');
      setL5Capabilities(response.data || []);
      const statsResponse = await apiClient.get('/memory/statistics');
      setL5Stats(statsResponse.data.l5_capabilities || { total_capabilities: 0 });
    } catch (error) {
      console.error('Failed to fetch L5 data:', error);
    }
  };

  useEffect(() => {
    fetchAllData();
  }, []);

  const getLevelName = (level: number) => {
    const names = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL', 'EMERGENCY'];
    return names[level] || 'UNKNOWN';
  };

  // 搜索处理
  const handleSearch = async () => {
    if (!searchKeyword.trim()) {
      toast.warning(t('events.searchKeywordRequired'));
      return;
    }

    setLoading(true);
    try {
      const response = await apiClient.post('/memory/search', {
        query: searchKeyword,
        limit: 20,
        search_type: 'hybrid',
      });
      const results = response.data || [];

      if (results.length > 0) {
        setActiveTab('l3');
        setL3Results(results);
        toast.success(t('events.searchFound', { count: results.length }));
      } else {
        toast.warning(t('events.searchEmpty'));
      }
    } catch (error: any) {
      const errorMessage = error?.response?.data?.detail || error?.message || 'unknown';
      toast.error(t('events.searchFailed', { message: errorMessage }));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4 text-sm">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{t('events.title')}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t('events.subtitle')}</p>
        </div>
        <Button onClick={fetchAllData} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          {t('events.refresh')}
        </Button>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid h-auto grid-cols-2 gap-1 md:grid-cols-5">
          <TabsTrigger value="l1"><Database className="mr-1 h-4 w-4" />{t('events.tabs.l1')} ({l1Stats.total})</TabsTrigger>
          <TabsTrigger value="l2"><GitBranch className="mr-1 h-4 w-4" />{t('events.tabs.l2')} ({l2Stats.total_relations})</TabsTrigger>
          <TabsTrigger value="l3"><Network className="mr-1 h-4 w-4" />{t('events.tabs.l3')} ({l3Stats.total_embeddings})</TabsTrigger>
          <TabsTrigger value="l4"><FileText className="mr-1 h-4 w-4" />{t('events.tabs.l4')} ({l4Stats.total_summaries})</TabsTrigger>
          <TabsTrigger value="l5"><Zap className="mr-1 h-4 w-4" />{t('events.tabs.l5')} ({l5Stats.total_capabilities})</TabsTrigger>
        </TabsList>

        <TabsContent value="l1" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('events.l1.totalEvents')}</p><p className="mt-1 text-2xl font-semibold">{l1Stats.total}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">INFO</p><p className="mt-1 text-2xl font-semibold text-emerald-600">{l1Events.filter((e) => e.level === 1).length}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">WARNING</p><p className="mt-1 text-2xl font-semibold text-amber-600">{l1Events.filter((e) => e.level === 2).length}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">ERROR+</p><p className="mt-1 text-2xl font-semibold text-red-600">{l1Events.filter((e) => e.level >= 3).length}</p></CardContent></Card>
          </div>
          <Card>
            <CardHeader><CardTitle>{t('events.l1.rawEvents')}</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {loading ? <LoadingSpinner /> : l1Events.map((event) => (
                <details key={event.id} className="rounded-md border p-3">
                  <summary className="cursor-pointer text-sm">
                    <span className="mr-2 font-medium">{event.type}</span>
                    <Badge variant="outline" className="mr-2">{getLevelName(event.level)}</Badge>
                    <span className="text-xs text-muted-foreground">{new Date(event.timestamp * 1000).toLocaleString()}</span>
                  </summary>
                  <div className="mt-2 grid gap-2 text-xs">
                    <div>ID: {event.id}</div>
                    <div>{t('events.l1.correlationId')}: {event.correlation_id || '-'}</div>
                    <div>{t('events.l1.source')}: {event.source || '-'}</div>
                    <pre className="max-h-52 overflow-auto rounded bg-muted p-2">{JSON.stringify(event.data, null, 2)}</pre>
                  </div>
                </details>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="l2" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('events.l2.totalEvents')}</p><p className="mt-1 text-2xl font-semibold">{l2Stats.total_events}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('events.l2.totalRelations')}</p><p className="mt-1 text-2xl font-semibold">{l2Stats.total_relations}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('events.l2.avgRelationPerEvent')}</p><p className="mt-1 text-2xl font-semibold">{l2Stats.total_events > 0 ? (l2Stats.total_relations / l2Stats.total_events).toFixed(2) : '0'}</p></CardContent></Card>
          </div>
          <Card>
            <CardHeader><CardTitle>{t('events.l2.relationDoc')}</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div><Badge variant="outline" className="mr-2">PRECEDE</Badge>{t('events.l2.precedeDesc')}</div>
              <div><Badge variant="outline" className="mr-2">TRIGGER</Badge>{t('events.l2.triggerDesc')}</div>
              <div><Badge variant="outline" className="mr-2">CAUSE</Badge>{t('events.l2.causeDesc')}</div>
              <div><Badge variant="outline" className="mr-2">FOLLOW</Badge>{t('events.l2.followDesc')}</div>
              <div><Badge variant="outline" className="mr-2">SAME_USER</Badge>{t('events.l2.sameUserDesc')}</div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="l3" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('events.l3.embeddingCount')}</p><p className="mt-1 text-2xl font-semibold">{l3Stats.total_embeddings}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('events.l3.vectorDimension')}</p><p className="mt-1 text-2xl font-semibold">{l3Stats.dimension}</p></CardContent></Card>
          </div>
          <Card>
            <CardHeader><CardTitle>{t('events.l3.semanticSearch')}</CardTitle></CardHeader>
            <CardContent>
              <div className="flex gap-2">
                <Input
                  placeholder={t('events.l3.searchPlaceholder')}
                  value={searchKeyword}
                  onChange={(e) => setSearchKeyword(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      void handleSearch();
                    }
                  }}
                />
                <Button onClick={handleSearch} disabled={loading}>
                  <Search className="mr-1 h-4 w-4" />
                  {t('events.l3.search')}
                </Button>
              </div>
            </CardContent>
          </Card>
          {l3Results.length > 0 && (
            <Card>
              <CardHeader><CardTitle>{t('events.l3.results')}</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {l3Results.map((item) => (
                  <div key={item.event_id} className="rounded-md border p-3 text-sm">
                    <div className="font-medium">{item.event_id.slice(0, 12)}...</div>
                    <div className="mt-1 text-muted-foreground">{item.text}</div>
                    <div className="mt-1 text-xs text-muted-foreground">{t('events.l3.type')}：{item.metadata?.event_type || '-'}</div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="l4" className="space-y-4">
          <Card>
            <CardContent className="p-4">
              <p className="text-xs text-muted-foreground">{t('events.l4.summaryTotal')}</p>
              <p className="mt-1 text-2xl font-semibold">{l4Stats.total_summaries}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>{t('events.l4.summaryDoc')}</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p>{t('events.l4.summaryExplain')}</p>
              <div className="flex gap-2">
                <Badge variant="outline">{t('events.l4.hour')}</Badge>
                <Badge variant="outline">{t('events.l4.day')}</Badge>
                <Badge variant="outline">{t('events.l4.week')}</Badge>
                <Badge variant="outline">{t('events.l4.month')}</Badge>
              </div>
              <p className="text-muted-foreground">{t('events.l4.summaryHint')}</p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="l5" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('events.l5.capabilityTotal')}</p><p className="mt-1 text-2xl font-semibold">{l5Stats.total_capabilities}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('events.l5.highSuccess')}</p><p className="mt-1 text-2xl font-semibold text-emerald-600">{l5Capabilities.filter((c) => c.success_rate > 0.8).length}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{t('events.l5.lowSuccess')}</p><p className="mt-1 text-2xl font-semibold text-red-600">{l5Capabilities.filter((c) => c.success_rate < 0.5).length}</p></CardContent></Card>
          </div>
          <Card>
            <CardHeader><CardTitle>{t('events.l5.list')}</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {l5Capabilities.map((capability) => (
                <div key={capability.capability_id} className="rounded-md border p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{capability.name}</span>
                    <Badge
                      variant={
                        capability.success_rate > 0.7 ? 'success' : capability.success_rate > 0.5 ? 'warning' : 'destructive'
                      }
                    >
                      {(capability.success_rate * 100).toFixed(0)}%
                    </Badge>
                  </div>
                  <p className="mt-1 text-muted-foreground">{capability.description}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{t('events.l5.usageCount')}：{capability.usage_count}</p>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default EventsPage;
