/**
 * Memory page – L0–L4 memory system.
 *
 * Refactored to use useMemory hook and extracted tab components.
 */
import React, { useState } from 'react';
import { RefreshCw, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { useMemory } from '@/hooks/useMemory';
import {
  L0Tab,
  L1Tab,
  L2Tab,
  L3Tab,
  L4Tab,
  ClearMemoryDialog,
} from '@/components/memory';

// Re-export for tests
const CONFIRM_WAIT_SECONDS = 3;
export { CONFIRM_WAIT_SECONDS };

const EventsPage: React.FC = () => {
  const { t } = useTranslation('app');
  const [activeTab, setActiveTab] = useState('l0');

  const {
    loading,
    stats,
    l0Sessions,
    l0Workbench,
    selectedSessionId,
    selectSession,
    l1Events,
    l2Relations,
    l2Assertions,
    l2Stats,
    identityLinks,
    l2Entities,
    l2Mentions,
    l2Snapshots,
    l2ConflictRules,
    l2ActionLoading,
    submitManualL2Event,
    replayL2Extraction,
    runL2Reconcile,
    runL2SnapshotRefresh,
    upsertL2GraphConflictRule,
    l3Summaries,
    l4Skills,
    searchQuery,
    setSearchQuery,
    searching,
    handleSearch,
    clearDialogOpen,
    setClearDialogOpen,
    clearConfirmText,
    setClearConfirmText,
    clearing,
    handleClearRequest,
    handleClearConfirm,
    refresh,
  } = useMemory();

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{t('memory.title')}</h1>
          <p className="text-muted-foreground">{t('memory.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => refresh(activeTab)} disabled={loading}>
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
          {loading ? (
            <LoadingSpinner />
          ) : (
            <L0Tab
              stats={stats.l0}
              sessions={l0Sessions}
              workbench={l0Workbench}
              selectedSessionId={selectedSessionId}
              onSelectSession={selectSession}
            />
          )}
        </TabsContent>
        <TabsContent value="l1" className="mt-4">
          {loading ? (
            <LoadingSpinner />
          ) : (
            <L1Tab stats={stats.l1} events={l1Events} />
          )}
        </TabsContent>
        <TabsContent value="l2" className="mt-4">
          {loading ? (
            <LoadingSpinner />
          ) : (
            <L2Tab
              stats={l2Stats}
              relations={l2Relations}
              assertions={l2Assertions}
              identityLinks={identityLinks}
              entities={l2Entities}
              mentions={l2Mentions}
              snapshots={l2Snapshots}
              conflictRules={l2ConflictRules}
              events={l1Events}
              actionLoading={l2ActionLoading}
              onSubmitManualEvent={submitManualL2Event}
              onReplayExtraction={replayL2Extraction}
              onRunReconcile={runL2Reconcile}
              onRunSnapshotRefresh={runL2SnapshotRefresh}
              onUpsertGraphConflictRule={upsertL2GraphConflictRule}
            />
          )}
        </TabsContent>
        <TabsContent value="l3" className="mt-4">
          {loading ? (
            <LoadingSpinner />
          ) : (
            <L3Tab stats={stats.l3} summaries={l3Summaries} />
          )}
        </TabsContent>
        <TabsContent value="l4" className="mt-4">
          {loading ? (
            <LoadingSpinner />
          ) : (
            <L4Tab stats={stats.l4} skills={l4Skills} />
          )}
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
      <ClearMemoryDialog
        open={clearDialogOpen}
        onOpenChange={setClearDialogOpen}
        confirmText={clearConfirmText}
        onConfirmTextChange={setClearConfirmText}
        clearing={clearing}
        onConfirm={handleClearConfirm}
      />
    </div>
  );
};

export default EventsPage;
