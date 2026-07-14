import { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  formatCount,
  formatTime,
  getRecordListCopy,
  getRowStatusClass,
  getStatusToneClass,
  type LayerRecord,
  type LayerSummary,
  type MaintenanceCategoryId,
} from '../governanceModel';

export function LayerWorkspace({
  layers,
  activeLayer,
  visibleRecords,
  page,
  pageCount,
  pageSize,
  totalRecordCount,
  recordSearchQuery,
  onSelectLayer,
  onRecordSearchChange,
  onSelectRecord,
  onPageChange,
  label,
}: {
  layers: LayerSummary[];
  activeLayer: MaintenanceCategoryId;
  visibleRecords: LayerRecord[];
  page: number;
  pageCount: number;
  pageSize: number;
  totalRecordCount: number;
  recordSearchQuery: string;
  onSelectLayer: (layer: MaintenanceCategoryId) => void;
  onRecordSearchChange: (value: string) => void;
  onSelectRecord: (record: LayerRecord) => void;
  onPageChange: (page: number) => void;
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
}) {
  const [draftSearchQuery, setDraftSearchQuery] = useState(recordSearchQuery);
  const isComposingSearchRef = useRef(false);
  const lastCommittedSearchQueryRef = useRef(recordSearchQuery);
  const selectedLayer = layers.find((layer) => layer.id === activeLayer) || layers[0];
  const displayRecordCount = Math.max(0, totalRecordCount);
  const isSearching = recordSearchQuery.trim().length > 0;
  const showSearch = displayRecordCount > 0 || isSearching;
  const pageStart = displayRecordCount === 0 || visibleRecords.length === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = pageStart === 0 ? 0 : Math.min(displayRecordCount, pageStart + visibleRecords.length - 1);

  useEffect(() => {
    if (isComposingSearchRef.current) return;
    setDraftSearchQuery(recordSearchQuery);
    lastCommittedSearchQueryRef.current = recordSearchQuery;
  }, [recordSearchQuery]);

  const commitSearchQuery = (value: string) => {
    if (value === lastCommittedSearchQueryRef.current) return;
    lastCommittedSearchQueryRef.current = value;
    onRecordSearchChange(value);
  };

  return (
    <section className="grid min-h-full gap-6 lg:h-full lg:min-h-0 lg:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="min-w-0 lg:min-h-0">
        <div className="px-2 pb-3 text-xs font-medium tracking-wide text-[hsl(var(--memory-muted))]">
          {label('objects.choose', '选择对象')}
        </div>
        <div className="flex gap-2 overflow-x-auto pb-2 [scrollbar-width:thin] lg:max-h-[min(560px,calc(100vh-330px))] lg:flex-col lg:gap-1 lg:overflow-y-auto lg:pr-2 [&::-webkit-scrollbar]:h-1.5 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-[hsl(var(--memory-divider)/0.72)]">
          {layers.map((layer) => (
            <button
              key={layer.id}
              type="button"
              aria-pressed={layer.id === activeLayer}
              onClick={() => onSelectLayer(layer.id)}
              className={cn(
                'flex min-w-[210px] items-center justify-between rounded-lg px-3 py-3 text-left transition-colors duration-200 lg:min-w-0 lg:w-full',
                layer.id === activeLayer
                  ? 'bg-[hsl(var(--memory-accent-soft)/0.56)]'
                  : 'hover:bg-[hsl(var(--memory-panel-subtle)/0.62)]'
              )}
            >
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-[hsl(var(--memory-title))]">{layer.label}</span>
                <span className="mt-1 block truncate text-xs leading-5 text-[hsl(var(--memory-muted))]">{layer.description}</span>
              </span>
              <span className="ml-4 shrink-0 text-right">
                <span className="block text-xs font-semibold tabular-nums text-[hsl(var(--memory-body))]">{formatCount(layer.count)}</span>
                {layer.tone !== 'ok' ? (
                  <span className={cn('mt-1 inline-flex rounded-sm px-1.5 py-0.5 text-[10px] ring-1', getStatusToneClass(layer.tone))}>
                    {layer.status}
                  </span>
                ) : null}
              </span>
            </button>
          ))}
        </div>
      </aside>

      <div className="flex min-h-[430px] min-w-0 flex-col rounded-xl bg-[hsl(var(--memory-panel-elevated)/0.74)] lg:min-h-0">
        <div className="flex flex-col gap-4 px-5 pb-4 pt-5 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold tracking-[-0.02em] text-[hsl(var(--memory-title))]">{selectedLayer.label}</h2>
            <p className="mt-1.5 text-sm leading-6 text-[hsl(var(--memory-body))]">
              {label('objects.tableSubtitle', '{{description}}（共 {{count}} 条）', {
                description: selectedLayer.description,
                count: formatCount(displayRecordCount),
              })}
            </p>
          </div>
          {showSearch ? (
            <label className="relative block w-full min-w-0 md:w-[280px]">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--memory-muted))]" />
              <input
                type="search"
                aria-label={label('objects.searchLabel', '搜索当前选项记录')}
                placeholder={label('objects.searchPlaceholder', '搜索当前选项记录')}
                value={draftSearchQuery}
                onCompositionStart={() => {
                  isComposingSearchRef.current = true;
                }}
                onCompositionEnd={(event) => {
                  isComposingSearchRef.current = false;
                  const value = event.currentTarget.value;
                  setDraftSearchQuery(value);
                  commitSearchQuery(value);
                }}
                onChange={(event) => {
                  const value = event.target.value;
                  setDraftSearchQuery(value);
                  if (!isComposingSearchRef.current) {
                    commitSearchQuery(value);
                  }
                }}
                className="h-10 w-full rounded-lg border border-[hsl(var(--memory-input-border)/0.56)] bg-[hsl(var(--memory-input-bg)/0.84)] pl-9 pr-3 text-sm text-[hsl(var(--memory-title))] outline-none transition-colors duration-200 placeholder:text-[hsl(var(--memory-muted))] hover:border-[hsl(var(--memory-input-border)/0.8)] focus:border-[hsl(var(--memory-accent)/0.48)] focus:ring-2 focus:ring-[hsl(var(--memory-accent)/0.12)]"
              />
            </label>
          ) : null}
        </div>

        {!isSearching && displayRecordCount === 0 ? (
          <div className="flex min-h-0 flex-1 items-start justify-center px-6 pt-[clamp(3.5rem,11vh,7rem)]">
            <div className="max-w-md text-center">
              <h3 className="text-lg font-semibold tracking-[-0.015em] text-[hsl(var(--memory-title))]">
                {label('objects.emptyTitle', '还没有{{category}}记录', { category: selectedLayer.label })}
              </h3>
              <p className="mt-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
                {label('objects.emptyBody', 'Magi 会从对话和已连接的来源中逐步整理这类记忆。')}
              </p>
              <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
                <Button asChild size="sm" variant="secondary" className="rounded-lg px-4">
                  <Link to="/memory/sources">{label('objects.addSource', '添加来源')}</Link>
                </Button>
                <Button asChild size="sm" variant="ghost" className="rounded-lg px-4">
                  <Link to="/chat">{label('objects.startChat', '开始对话')}</Link>
                </Button>
              </div>
            </div>
          </div>
        ) : visibleRecords.length === 0 ? (
          <div className="flex min-h-0 flex-1 items-start justify-center px-6 pt-[clamp(3.5rem,11vh,7rem)]">
            <div className="max-w-sm text-center">
              <h3 className="text-base font-semibold text-[hsl(var(--memory-title))]">
                {label('objects.searchEmptyTitle', '没有匹配结果')}
              </h3>
              <p className="mt-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
                {label('objects.searchEmptyBody', '换个关键词，或清除搜索后查看全部记录。')}
              </p>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="mt-3 rounded-lg px-4"
                onClick={() => {
                  setDraftSearchQuery('');
                  commitSearchQuery('');
                }}
              >
                {label('objects.clearSearch', '清除搜索')}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="min-h-0 flex-1 overflow-x-auto [scrollbar-width:thin] [&::-webkit-scrollbar]:h-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[hsl(var(--memory-divider)/0.8)]">
              <div className="min-w-[720px]">
                <div className="mx-2 grid grid-cols-[minmax(230px,1.35fr)_104px_112px_112px_88px_32px] rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.48)] px-3 py-2.5 text-xs font-medium text-[hsl(var(--memory-muted))]">
                  <span>{label('fields.content', '内容')}</span>
                  <span>{label('fields.type', '类型')}</span>
                  <span>{label('fields.source', '来源')}</span>
                  <span>{label('fields.updatedAt', '更新时间')}</span>
                  <span>{label('fields.status', '状态')}</span>
                  <span />
                </div>
                <div className="max-h-[390px] space-y-1 overflow-y-auto px-2 pb-2 pt-1 [scrollbar-width:thin] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-[hsl(var(--memory-divider)/0.72)]">
                  {visibleRecords.map((record) => {
                    const listCopy = getRecordListCopy(record, label);
                    return (
                      <button
                        key={`${record.categoryId}:${record.id}`}
                        type="button"
                        aria-label={label('objects.openRecord', '打开记录 {{title}}', { title: listCopy.title })}
                        onClick={() => onSelectRecord(record)}
                        className="grid w-full grid-cols-[minmax(230px,1.35fr)_104px_112px_112px_88px_32px] items-center rounded-lg px-3 py-3 text-left text-xs transition-colors duration-200 hover:bg-[hsl(var(--memory-panel-subtle)/0.58)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.14)]"
                      >
                        <span className="min-w-0">
                          <span className="block truncate font-medium text-[hsl(var(--memory-title))]">{listCopy.title}</span>
                          {listCopy.subtitle ? (
                            <span className="mt-0.5 block truncate text-[11px] text-[hsl(var(--memory-muted))]">{listCopy.subtitle}</span>
                          ) : null}
                        </span>
                        <span className="truncate text-[hsl(var(--memory-body))]">{record.type}</span>
                        <span className="truncate text-[hsl(var(--memory-body))]">{record.source}</span>
                        <span className="text-[hsl(var(--memory-body))]">{formatTime(record.updatedAt)}</span>
                        <span className={cn('font-medium', getRowStatusClass(record.status))}>{record.status}</span>
                        <ChevronRight className="h-4 w-4 text-[hsl(var(--memory-muted))]" />
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
            <div className="flex flex-col gap-3 px-5 py-4 text-sm text-[hsl(var(--memory-body))] sm:flex-row sm:items-center sm:justify-between">
              <span>
                {label('objects.pageSummary', '{{start}}-{{end}} / {{total}} 条', {
                  start: pageStart,
                  end: pageEnd,
                  total: displayRecordCount,
                })}
              </span>
              <div className="flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  className="h-8 rounded-lg px-3"
                  disabled={page <= 1}
                  onClick={() => onPageChange(page - 1)}
                >
                  <ChevronLeft className="mr-1 h-4 w-4" />
                  {label('objects.prevPage', '上一页')}
                </Button>
                <span className="min-w-[56px] text-center text-xs text-[hsl(var(--memory-muted))]">
                  {label('objects.pageIndex', '{{page}} / {{pageCount}}', { page, pageCount })}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  className="h-8 rounded-lg px-3"
                  disabled={page >= pageCount}
                  onClick={() => onPageChange(page + 1)}
                >
                  {label('objects.nextPage', '下一页')}
                  <ChevronRight className="ml-1 h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
