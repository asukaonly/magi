import type { ReactNode } from 'react';
import { Loader2, RefreshCw, SlidersHorizontal, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
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
  onReplay,
  onInvalidate,
  onDelete,
  onCascadeForget,
}: {
  record: LayerRecord | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
  actionLoading: boolean;
  onReplay: () => void;
  onInvalidate: () => void;
  onDelete: () => void;
  onCascadeForget: () => void;
}) {
  const replayAction = record ? getReplayActionCopy(record, label) : null;
  const canInvalidate = record?.categoryId === 'assertions' || record?.categoryId === 'relations';
  const canDelete = record?.categoryId === 'events';
  const canCascadeForget = record?.categoryId === 'entities';
  const hasMaintenanceActions = Boolean(replayAction || canInvalidate || canDelete || canCascadeForget);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex !w-[min(96vw,720px)] !max-w-[720px] flex-col overflow-y-auto border-[hsl(var(--memory-border)/0.65)] bg-[hsl(var(--memory-panel))] p-0"
      >
        <SheetHeader className="border-b border-[hsl(var(--memory-divider)/0.58)] px-5 py-5">
          <SheetTitle className="text-lg text-[hsl(var(--memory-title))]">{label('drawer.title', '记录详情')}</SheetTitle>
          <SheetDescription className="text-[hsl(var(--memory-body))]">
            {record ? `${record.categoryLabel} · ${record.id}` : label('drawer.empty', '选择一条记录查看详情。')}
          </SheetDescription>
        </SheetHeader>

        {record ? (
          <div className="flex flex-1 flex-col gap-4 px-5 py-4">
            <section>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{record.title}</h2>
                  <p className="mt-1 text-sm leading-6 text-[hsl(var(--memory-body))]">{record.summary || label('drawer.noSummary', '暂无摘要。')}</p>
                </div>
                <span className={cn('shrink-0 rounded-full px-2.5 py-1 text-xs font-medium', getRowStatusClass(record.status))}>{record.status}</span>
              </div>
            </section>

            <DetailGroup title={label('drawer.metadata', '元数据')}>
              <DetailRow label="ID" value={record.id} />
              <DetailRow label={label('fields.type', '类型')} value={record.type} />
              <DetailRow label={label('fields.source', '来源')} value={record.source} />
              <DetailRow label={label('fields.updatedAt', '更新时间')} value={formatTime(record.updatedAt)} />
              <DetailRow label={label('fields.evidenceCount', '证据数')} value={record.evidenceCount ?? '-'} />
            </DetailGroup>

            <DetailGroup title={label('drawer.related', '来源证据')}>
              {record.related && record.related.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {record.related.slice(0, 12).map((item) => (
                    <span key={item} className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.78)] px-2.5 py-1 text-xs text-[hsl(var(--memory-body))]">
                      {item}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-[hsl(var(--memory-muted))]">{label('drawer.noRelated', '没有可直接展示的证据引用。')}</p>
              )}
            </DetailGroup>

            <DetailGroup title={label('drawer.impact', '下游影响')}>
              {record.impact && record.impact.length > 0 ? (
                <div className="grid gap-2 sm:grid-cols-3">
                  {record.impact.map((item) => (
                    <div key={item.label} className="rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.56)] px-3 py-2">
                      <div className="text-xs text-[hsl(var(--memory-muted))]">{item.label}</div>
                      <div className="mt-1 text-base font-semibold text-[hsl(var(--memory-title))]">{item.value}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-[hsl(var(--memory-muted))]">{label('drawer.noImpact', '暂无可计算的下游影响。')}</p>
              )}
            </DetailGroup>

            <div className="mt-auto space-y-3 border-t border-[hsl(var(--memory-divider)/0.58)] pt-4">
              <div>
                <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">{label('drawer.safeActions', '维护操作')}</div>
                {replayAction ? <p className="mt-1.5 text-xs leading-5 text-[hsl(var(--memory-muted))]">{replayAction.hint}</p> : null}
                {hasMaintenanceActions ? (
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    {replayAction ? (
                      <Button variant="outline" className="h-9 rounded-sm" onClick={onReplay} disabled={actionLoading}>
                        {actionLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
                        {replayAction.buttonLabel}
                      </Button>
                    ) : null}
                    {canInvalidate ? (
                      <Button variant="outline" className="h-9 rounded-sm" onClick={onInvalidate} disabled={actionLoading}>
                        {actionLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <SlidersHorizontal className="mr-2 h-4 w-4" />}
                        {label('drawer.actions.invalidate', '标记无效')}
                      </Button>
                    ) : null}
                    {canDelete ? (
                      <Button variant="outline" className="h-9 rounded-sm border-red-200 text-red-700 hover:bg-red-50" onClick={onDelete} disabled={actionLoading}>
                        {actionLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                        {label('drawer.actions.delete', '删除')}
                      </Button>
                    ) : null}
                  </div>
                ) : (
                  <p className="mt-2 text-xs leading-5 text-[hsl(var(--memory-muted))]">
                    {label('drawer.noActions', '这个类型目前只能查看。')}
                  </p>
                )}
              </div>
              {canCascadeForget ? (
                <Button className="h-10 w-full rounded-sm bg-red-600 text-white hover:bg-red-700" onClick={onCascadeForget} disabled={actionLoading}>
                  {actionLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                  {label('drawer.actions.cascadeForget', '连带遗忘（包含下游）')}
                </Button>
              ) : null}
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
      enabled: true,
      buttonLabel: label('drawer.actions.reprocessEvent', '重新抽取结构'),
      hint: label('drawer.reprocessEventHint', '把这条原始事件重新送入结构抽取，更新实体、断言和关系。'),
    };
  }

  if (record.categoryId === 'entities') {
    return {
      buttonLabel: label('drawer.actions.reprocessEntity', '重新校准实体'),
      hint: label('drawer.reprocessEntityHint', '重新核对这个实体的合并、关系和冲突状态。'),
    };
  }

  return null;
}

function DetailGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-elevated)/0.58)] p-3">
      <h3 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-3 border-b border-[hsl(var(--memory-divider)/0.36)] py-1.5 text-sm last:border-b-0">
      <div className="text-[hsl(var(--memory-muted))]">{label}</div>
      <div className="min-w-0 break-words text-[hsl(var(--memory-title))]">{value}</div>
    </div>
  );
}
