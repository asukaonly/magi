import { ChevronLeft, ChevronRight, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { MEMORY_EMPTY_PANEL_CLASS } from '../MemoryPageFrame';
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
  activeRecords,
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
  activeRecords: LayerRecord[];
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
  const selectedLayer = layers.find((layer) => layer.id === activeLayer) || layers[0];
  const displayRecordCount = Math.max(0, totalRecordCount);
  const pageStart = displayRecordCount === 0 || visibleRecords.length === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = pageStart === 0 ? 0 : Math.min(displayRecordCount, pageStart + visibleRecords.length - 1);
  return (
    <section className="grid h-full min-h-0 gap-3 lg:grid-cols-[230px_minmax(0,1fr)]">
      <aside className="min-h-0 rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.66)] p-2">
        <div className="px-2 pb-2 pt-1 text-xs font-medium text-[hsl(var(--memory-muted))]">
          {label('objects.choose', '选择对象')}
        </div>
        <div className="max-h-[min(530px,calc(100vh-340px))] space-y-1.5 overflow-y-auto pr-1 [scrollbar-width:thin] [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[hsl(var(--memory-divider)/0.8)]">
          {layers.map((layer) => (
            <button
              key={layer.id}
              type="button"
              onClick={() => onSelectLayer(layer.id)}
              className={cn(
                'flex w-full items-center justify-between rounded-lg border px-3 py-3 text-left text-xs transition-colors',
                layer.id === activeLayer
                  ? 'border-[hsl(var(--memory-accent)/0.36)] bg-[hsl(var(--memory-accent-soft)/0.45)]'
                  : 'border-transparent hover:bg-[hsl(var(--memory-panel-subtle)/0.58)]'
              )}
            >
              <span className="min-w-0">
                <span className="block text-xs font-semibold text-[hsl(var(--memory-title))]">{layer.label}</span>
                <span className="mt-1 block truncate text-xs text-[hsl(var(--memory-muted))]">{layer.description}</span>
              </span>
              <span className="ml-3 shrink-0 text-right">
                <span className="block text-xs font-medium text-[hsl(var(--memory-title))]">{formatCount(layer.count)}</span>
                <span className={cn('mt-1 inline-flex rounded-full px-2 py-0.5 text-[11px] ring-1', getStatusToneClass(layer.tone))}>
                  {layer.status}
                </span>
              </span>
            </button>
          ))}
        </div>
      </aside>

      <div className="flex min-h-0 min-w-0 flex-col rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.66)]">
        <div className="flex flex-col gap-3 border-b border-[hsl(var(--memory-divider)/0.58)] px-4 py-3 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{selectedLayer.label}</h2>
            <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">
              {label('objects.tableSubtitle', '{{description}}（共 {{count}} 条）', {
                description: selectedLayer.description,
                count: formatCount(selectedLayer.count),
              })}
            </p>
          </div>
          <label className="relative block w-full min-w-0 md:w-[260px]">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--memory-muted))]" />
            <input
              type="search"
              aria-label={label('objects.searchLabel', '搜索当前页记录')}
              placeholder={label('objects.searchPlaceholder', '搜索当前页记录')}
              value={recordSearchQuery}
              onChange={(event) => onRecordSearchChange(event.target.value)}
              className="h-9 w-full rounded-sm border border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] pl-9 pr-3 text-sm text-[hsl(var(--memory-title))] outline-none transition-colors placeholder:text-[hsl(var(--memory-muted))] focus:border-[hsl(var(--memory-accent)/0.58)] focus:ring-2 focus:ring-[hsl(var(--memory-accent)/0.16)]"
            />
          </label>
        </div>

        {activeRecords.length === 0 ? (
          <div className="min-h-0 flex-1 p-4">
            <div className={MEMORY_EMPTY_PANEL_CLASS}>{label('objects.empty', '这个对象类型暂时没有可展示的记录。')}</div>
          </div>
        ) : visibleRecords.length === 0 ? (
          <div className="min-h-0 flex-1 p-4">
            <div className={MEMORY_EMPTY_PANEL_CLASS}>{label('objects.searchEmpty', '当前页没有匹配的记录。')}</div>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="min-h-0 flex-1 overflow-x-auto [scrollbar-width:thin] [&::-webkit-scrollbar]:h-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[hsl(var(--memory-divider)/0.8)]">
              <div className="min-w-[720px]">
                <div className="grid grid-cols-[minmax(230px,1.35fr)_104px_112px_112px_88px_32px] border-b border-[hsl(var(--memory-divider)/0.5)] px-4 py-2 text-xs font-medium text-[hsl(var(--memory-muted))]">
                  <span>{label('fields.content', '内容')}</span>
                  <span>{label('fields.type', '类型')}</span>
                  <span>{label('fields.source', '来源')}</span>
                  <span>{label('fields.updatedAt', '更新时间')}</span>
                  <span>{label('fields.status', '状态')}</span>
                  <span />
                </div>
                <div className="max-h-[390px] divide-y divide-[hsl(var(--memory-divider)/0.46)] overflow-y-auto [scrollbar-width:thin] [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[hsl(var(--memory-divider)/0.8)]">
                  {visibleRecords.map((record) => {
                    const listCopy = getRecordListCopy(record, label);
                    return (
                      <button
                        key={`${record.categoryId}:${record.id}`}
                        type="button"
                        aria-label={label('objects.openRecord', '打开记录 {{title}}', { title: listCopy.title })}
                        onClick={() => onSelectRecord(record)}
                        className="grid w-full grid-cols-[minmax(230px,1.35fr)_104px_112px_112px_88px_32px] items-center px-4 py-3 text-left text-xs transition-colors hover:bg-[hsl(var(--memory-panel-subtle)/0.48)]"
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
            <div className="flex flex-col gap-2 border-t border-[hsl(var(--memory-divider)/0.5)] px-4 py-3 text-sm text-[hsl(var(--memory-body))] sm:flex-row sm:items-center sm:justify-between">
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
                  variant="outline"
                  className="h-8 rounded-sm px-3"
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
                  variant="outline"
                  className="h-8 rounded-sm px-3"
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
