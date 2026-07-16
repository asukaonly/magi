import type { ReactNode } from 'react';
import { ChevronDown, Loader2, RefreshCw, SlidersHorizontal, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import MemoryCorrectionHistory from '@/components/memory/correction/MemoryCorrectionHistory';
import type { MemoryCorrectionUiTarget } from '@/components/memory/correction/memoryCorrectionModel';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { cn } from '@/lib/utils';
import {
  formatTime,
  getRowStatusClass,
  type LayerRecord,
} from '../governanceModel';

export function RecordDrawer({
  record,
  open,
  onOpenChange,
  label,
  actionLoading,
  correctionTarget,
  onReplay,
  onCorrect,
  onCorrectionReverted,
  onCorrectionConflict,
  onDelete,
  onCascadeForget,
}: {
  record: LayerRecord | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
  actionLoading: boolean;
  correctionTarget: MemoryCorrectionUiTarget | null;
  onReplay: () => void;
  onCorrect: () => void;
  onCorrectionReverted: () => void | Promise<void>;
  onCorrectionConflict: () => void | Promise<void>;
  onDelete: () => void;
  onCascadeForget: () => void;
}) {
  const replayAction = record ? getReplayActionCopy(record, label) : null;
  const canCorrect = Boolean(correctionTarget && record?.correction?.correctable);
  const canDelete = record?.categoryId === 'events';
  const canCascadeForget = record?.categoryId === 'entities';
  const hasMaintenanceActions = Boolean(replayAction || canCorrect || canDelete || canCascadeForget);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        closeLabel={label('drawer.close', '关闭')}
        className="flex !w-[min(96vw,760px)] !max-w-[760px] flex-col overflow-y-auto border-[hsl(var(--memory-border)/0.65)] bg-[hsl(var(--memory-panel))] p-0"
      >
        <SheetHeader className="border-b border-[hsl(var(--memory-divider)/0.58)] px-6 py-5">
          <SheetTitle className="text-lg text-[hsl(var(--memory-title))]">{label('drawer.title', '记录详情')}</SheetTitle>
          <SheetDescription className="text-sm text-[hsl(var(--memory-body))]">
            {record
              ? label('drawer.context', '{{category}} · {{source}}', { category: record.categoryLabel, source: record.source })
              : label('drawer.empty', '选择一条记录查看详情。')}
          </SheetDescription>
        </SheetHeader>

        {record ? (
          <div className="flex flex-1 flex-col px-6">
            <section className="py-5">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h2 className="text-base font-semibold leading-6 text-[hsl(var(--memory-title))]">{record.title}</h2>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[hsl(var(--memory-body))]">
                    {record.summary || label('drawer.noSummary', '暂无摘要。')}
                  </p>
                </div>
                <span className={cn('shrink-0 rounded-full bg-[hsl(var(--memory-panel-subtle)/0.72)] px-2.5 py-1 text-xs font-medium', getRowStatusClass(record.status))}>
                  {record.status}
                </span>
              </div>
            </section>

            {record.details && record.details.length > 0 ? (
              <DrawerSection title={label('drawer.readableDetails', '记录内容')}>
                <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
                  {record.details.map((item) => (
                    <div key={`${item.label}:${item.value}`} className="min-w-0">
                      <div className="text-xs text-[hsl(var(--memory-muted))]">{item.label}</div>
                      <div className="mt-1 break-words text-sm text-[hsl(var(--memory-title))]">{item.value}</div>
                    </div>
                  ))}
                </div>
              </DrawerSection>
            ) : null}

            <DrawerSection title={label('drawer.related', '来源依据')}>
              {record.related && record.related.length > 0 ? (
                <details className="group">
                  <summary className="flex cursor-pointer list-none items-center justify-between rounded-lg px-1 py-1 text-sm text-[hsl(var(--memory-body))] outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.14)]">
                    <span>{label('drawer.relatedCount', '关联 {{count}} 条来源记录', { count: record.related.length })}</span>
                    <span className="inline-flex items-center gap-1 text-xs text-[hsl(var(--memory-muted))]">
                      {label('drawer.showReferences', '查看引用编号')}
                      <ChevronDown className="h-4 w-4 transition-transform duration-200 group-open:rotate-180" aria-hidden="true" />
                    </span>
                  </summary>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {record.related.slice(0, 20).map((item) => (
                      <span key={item} className="max-w-full truncate rounded-md bg-[hsl(var(--memory-panel-subtle)/0.78)] px-2.5 py-1 text-xs text-[hsl(var(--memory-body))]">
                        {item}
                      </span>
                    ))}
                  </div>
                </details>
              ) : (
                <p className="text-sm text-[hsl(var(--memory-muted))]">{label('drawer.noRelated', '没有可直接展示的来源引用。')}</p>
              )}
            </DrawerSection>

            <DrawerSection title={label('drawer.visibleImpact', '当前可见关联')}>
              {record.impact && record.impact.length > 0 ? (
                <>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
                    {record.impact.map((item) => (
                      <div key={item.label}>
                        <div className="text-xs text-[hsl(var(--memory-muted))]">{item.label}</div>
                        <div className="mt-1 text-base font-semibold tabular-nums text-[hsl(var(--memory-title))]">{item.value}</div>
                      </div>
                    ))}
                  </div>
                  <p className="mt-3 text-xs leading-5 text-[hsl(var(--memory-muted))]">
                    {label('drawer.visibleImpactHint', '这里只反映当前已读取的数据，不代表删除或遗忘的完整影响范围。')}
                  </p>
                </>
              ) : (
                <p className="text-sm text-[hsl(var(--memory-muted))]">{label('drawer.noImpact', '暂无可展示的关联信息。')}</p>
              )}
            </DrawerSection>

            <DrawerSection>
              <details className="group">
                <summary className="flex cursor-pointer list-none items-center justify-between rounded-lg px-1 py-1 text-sm font-medium text-[hsl(var(--memory-title))] outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.14)]">
                  <span>{label('drawer.internalInfo', '内部信息')}</span>
                  <span className="inline-flex items-center gap-1 text-xs font-normal text-[hsl(var(--memory-muted))]">
                    {label('drawer.expandInternalInfo', '展开查看')}
                    <ChevronDown className="h-4 w-4 transition-transform duration-200 group-open:rotate-180" aria-hidden="true" />
                  </span>
                </summary>
                <div className="mt-3">
                  <DetailRow label="ID" value={record.id} />
                  <DetailRow label={label('fields.type', '类型')} value={record.type} />
                  <DetailRow label={label('fields.source', '来源')} value={record.source} />
                  <DetailRow label={label('fields.updatedAt', '更新时间')} value={formatTime(record.updatedAt)} />
                  <DetailRow label={label('fields.evidenceCount', '证据数')} value={record.evidenceCount ?? '-'} />
                </div>
              </details>
            </DrawerSection>

            {correctionTarget ? (
              <MemoryCorrectionHistory
                target={correctionTarget}
                onReverted={onCorrectionReverted}
                onConflict={onCorrectionConflict}
              />
            ) : null}

            <div className="mt-auto border-t border-[hsl(var(--memory-divider)/0.58)] py-5">
              <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">{label('drawer.safeActions', '维护操作')}</div>
              {replayAction ? <p className="mt-1.5 text-xs leading-5 text-[hsl(var(--memory-muted))]">{replayAction.hint}</p> : null}
              {hasMaintenanceActions ? (
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {replayAction ? (
                    <Button variant="outline" className="h-9 rounded-lg" onClick={onReplay} disabled={actionLoading}>
                      {actionLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
                      {replayAction.buttonLabel}
                    </Button>
                  ) : null}
                  {canCorrect ? (
                    <Button variant="outline" className="min-h-11 rounded-lg" onClick={onCorrect} disabled={actionLoading}>
                      {actionLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <SlidersHorizontal className="mr-2 h-4 w-4" />}
                      {label('drawer.actions.correctMemory', '修正这条记忆')}
                    </Button>
                  ) : null}
                  {canDelete ? (
                    <Button variant="outline" className="h-9 rounded-lg border-red-200 text-red-700 hover:bg-red-50 dark:border-red-900/60 dark:text-red-400 dark:hover:bg-red-950/30" onClick={onDelete} disabled={actionLoading}>
                      {actionLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                      {label('drawer.actions.deleteEvent', '删除原始事件')}
                    </Button>
                  ) : null}
                  {canCascadeForget ? (
                    <Button variant="outline" className="h-9 rounded-lg border-red-200 text-red-700 hover:bg-red-50 dark:border-red-900/60 dark:text-red-400 dark:hover:bg-red-950/30" onClick={onCascadeForget} disabled={actionLoading}>
                      {actionLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                      {label('drawer.actions.cascadeForgetEntity', '遗忘实体及相关知识')}
                    </Button>
                  ) : null}
                </div>
              ) : (
                <p className="mt-2 text-xs leading-5 text-[hsl(var(--memory-muted))]">
                  {correctionTarget
                    ? label('drawer.historicalMemoryHint', '这是历史记录，可查看修正历史或撤销最新修正。')
                    : label('drawer.noActions', '这个类型目前只能查看。')}
                </p>
              )}
            </div>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function getReplayActionCopy(
  record: LayerRecord,
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string
) {
  if (record.categoryId === 'events') {
    return {
      buttonLabel: label('drawer.actions.reprocessEventReadable', '重新提取'),
      hint: label('drawer.reprocessEventHint', '把这条原始事件重新送入结构抽取，更新实体、断言和关系。'),
    };
  }

  if (record.categoryId === 'entities') {
    return {
      buttonLabel: label('drawer.actions.reprocessEntityReadable', '重新核对'),
      hint: label('drawer.reprocessEntityHint', '重新核对这个实体的合并、关系和冲突状态。'),
    };
  }

  return null;
}

function DrawerSection({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="border-t border-[hsl(var(--memory-divider)/0.46)] py-5">
      {title ? <h3 className="mb-3 text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h3> : null}
      {children}
    </section>
  );
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[104px_minmax(0,1fr)] gap-3 border-b border-[hsl(var(--memory-divider)/0.32)] py-2 text-sm last:border-b-0">
      <div className="text-[hsl(var(--memory-muted))]">{label}</div>
      <div className="min-w-0 break-words text-[hsl(var(--memory-title))]">{value}</div>
    </div>
  );
}
