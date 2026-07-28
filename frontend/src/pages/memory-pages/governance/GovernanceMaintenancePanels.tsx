import { Link } from 'react-router';
import { AlertTriangle, ArrowUpRight, CheckCircle2, Loader2, Play } from 'lucide-react';
import { type EpisodeReconsolidateResult } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export function TaskMaintenancePanel({
  label,
}: {
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
}) {
  const rows = [
    [label('tasks.eventsTitle', '原始事件清理'), label('tasks.eventsBody', '压缩可清理事件、清除过期负载'), label('tasks.eventsScope', '事件维护'), label('statuses.enabled', '已启用')],
    [label('tasks.structureTitle', '结构抽取'), label('tasks.structureBody', '处理实体、断言和关系派生任务'), label('tasks.structureScope', '知识维护'), label('statuses.enabled', '已启用')],
    [label('tasks.chapterTitle', '章节整理'), label('tasks.chapterBody', '升级章节、经历和缺失总结'), label('tasks.chapterScope', '经历维护'), label('statuses.enabled', '已启用')],
    [label('tasks.summaryTitle', '总结生成'), label('tasks.summaryBody', '生成时段总结并清理过期内容'), label('tasks.summaryScope', '总结维护'), label('statuses.enabled', '已启用')],
    [label('tasks.skillsTitle', '工具记忆维护'), label('tasks.skillsBody', '维护工具技能和失败保护状态'), label('tasks.skillsScope', '技能维护'), label('statuses.enabled', '已启用')],
  ];
  return (
    <section className="rounded-xl bg-[hsl(var(--memory-panel-elevated)/0.74)] p-2">
      <div className="flex flex-col gap-3 px-3 pb-4 pt-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-[-0.02em] text-[hsl(var(--memory-title))]">{label('tasks.title', '记忆维护任务')}</h2>
          <p className="mt-1.5 text-sm leading-6 text-[hsl(var(--memory-body))]">{label('tasks.subtitle', '这里只聚合记忆相关任务；完整编辑仍在调度配置里。')}</p>
        </div>
        <Link to="/tasks/schedules" className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm font-medium text-[hsl(var(--memory-accent))] transition-colors duration-200 hover:bg-[hsl(var(--memory-accent-soft)/0.46)] hover:text-[hsl(var(--memory-title))]">
          {label('tasks.openSchedules', '打开调度配置')}
          <ArrowUpRight className="h-4 w-4" />
        </Link>
      </div>
      <div className="space-y-1">
        {rows.map(([name, description, scope, status]) => (
          <div key={name} className="grid gap-2 rounded-lg px-3 py-3 text-sm transition-colors duration-200 hover:bg-[hsl(var(--memory-panel-subtle)/0.54)] md:grid-cols-[170px_minmax(0,1fr)_140px_92px] md:items-center">
            <div className="font-semibold text-[hsl(var(--memory-title))]">{name}</div>
            <div className="leading-6 text-[hsl(var(--memory-body))]">{description}</div>
            <div className="truncate text-xs text-[hsl(var(--memory-muted))]">{scope}</div>
            <div className="inline-flex items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
              <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              {status}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export function ManualMaintenancePanel({
  label,
  reconsolidating,
  reconsolidateResult,
  reconsolidateError,
  onReconsolidate,
  onFlushMicrobatches,
  l2ActionLoading,
}: {
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
  reconsolidating: boolean;
  reconsolidateResult: EpisodeReconsolidateResult | null;
  reconsolidateError: string | null;
  onReconsolidate: () => Promise<void>;
  onFlushMicrobatches: () => Promise<void>;
  l2ActionLoading: boolean;
}) {
  return (
    <section className="rounded-xl bg-[hsl(var(--memory-panel-elevated)/0.74)] p-2">
      <ActionRow
        title={label('reconsolidateTitle', '整理章节')}
        description={label('reconsolidateBody', '让 Magi 把最近形成的活动片段升级成章节，并给它们起标题。')}
        buttonLabel={label('reconsolidateRunSpecific', '立即整理章节')}
        busy={reconsolidating}
        onClick={() => void onReconsolidate()}
      />
      <ActionRow
        title={label('manual.flushStructureTitle', '处理结构抽取积压')}
        description={label('manual.flushStructureBody', '立即提交当前暂存的结构抽取批次，适合调试抽取延迟。')}
        buttonLabel={label('manual.flushRun', '立即处理')}
        busy={l2ActionLoading}
        onClick={() => void onFlushMicrobatches()}
      />
      {reconsolidateResult ? (
        <div className="mx-1 mb-1 rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.54)] px-4 py-3 text-sm leading-6 text-[hsl(var(--memory-body))]">
          {label('reconsolidateResult', '升级 {{promoted}} 条 · 标志 {{standouts}} 条 · 新章节 {{summaries}} 条', {
            promoted: reconsolidateResult.promoted,
            standouts: reconsolidateResult.standouts,
            summaries: reconsolidateResult.summaries_generated,
          })}
        </div>
      ) : null}
      {reconsolidateError ? (
        <div className="mx-1 mb-1 rounded-lg bg-red-50 px-4 py-3 text-sm leading-6 text-red-700 dark:bg-red-950/30 dark:text-red-300">{reconsolidateError}</div>
      ) : null}
    </section>
  );
}

function ActionRow({
  title,
  description,
  buttonLabel,
  busy,
  onClick,
}: {
  title: string;
  description: string;
  buttonLabel: string;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <div className="flex flex-col gap-4 rounded-lg px-3 py-4 transition-colors duration-200 hover:bg-[hsl(var(--memory-panel-subtle)/0.48)] md:flex-row md:items-center md:justify-between">
      <div>
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
        <p className="mt-1.5 text-sm leading-6 text-[hsl(var(--memory-body))]">{description}</p>
      </div>
      <Button onClick={onClick} disabled={busy} className="h-9 w-fit rounded-lg px-4">
        {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
        {buttonLabel}
      </Button>
    </div>
  );
}

export function ForgetMaintenancePanel({
  label,
  onOpenObjects,
}: {
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
  onOpenObjects: (layer: 'events' | 'entities') => void;
}) {
  return (
    <section className="space-y-4">
      <div className="rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.48)] px-5 py-4 text-sm leading-6 text-[hsl(var(--memory-body))]">
        {label('forgetDrawerHint', '遗忘和删除从具体记录发起：先在「对象明细」里打开一条记录，再在抽屉中查看影响。')}
      </div>
      <div className="space-y-1 rounded-xl bg-[hsl(var(--memory-panel-elevated)/0.74)] p-2">
        <ObjectPanel onClick={() => onOpenObjects('events')} title={label('forgetBySource', '按来源/事件清理')} body={label('forgetBySourceBody', '在对象明细中按来源、时间和内容筛选原始事件。')} />
        <ObjectPanel onClick={() => onOpenObjects('entities')} title={label('forgetByEntity', '按实体处理')} body={label('forgetByEntityBody', '在对象明细中选择实体并查看遗忘影响。')} />
        <LinkPanel to="/memory/episodes" title={label('forgetByEpisode', '按经历处理')} body={label('forgetByEpisodeBody', '进入经历详情后处理章节边界和可见性。')} />
      </div>
    </section>
  );
}

function ObjectPanel({ onClick, title, body }: { onClick: () => void; title: string; body: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-between gap-5 rounded-lg px-4 py-4 text-left transition-colors duration-200 hover:bg-[hsl(var(--memory-panel-subtle)/0.56)]"
    >
      <div className="min-w-0">
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
        <p className="mt-1.5 text-sm leading-6 text-[hsl(var(--memory-body))]">{body}</p>
      </div>
      <ArrowUpRight className="h-4 w-4 shrink-0 text-[hsl(var(--memory-accent))]" />
    </button>
  );
}

function LinkPanel({ to, title, body }: { to: string; title: string; body: string }) {
  return (
    <Link
      to={to}
      className="flex items-center justify-between gap-5 rounded-lg px-4 py-4 transition-colors duration-200 hover:bg-[hsl(var(--memory-panel-subtle)/0.56)]"
    >
      <div className="min-w-0">
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
        <p className="mt-1.5 text-sm leading-6 text-[hsl(var(--memory-body))]">{body}</p>
      </div>
      <ArrowUpRight className="h-4 w-4 shrink-0 text-[hsl(var(--memory-accent))]" />
    </Link>
  );
}

export function DiagnosticsPanel({
  label,
  diagnostics,
}: {
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
  diagnostics: Array<{ id: string; severity: string; title: string; detail: string }>;
}) {
  return (
    <section className="rounded-xl bg-[hsl(var(--memory-panel-elevated)/0.74)] p-2">
      <div className="px-3 pb-4 pt-3">
        <h2 className="text-lg font-semibold tracking-[-0.02em] text-[hsl(var(--memory-title))]">{label('diagnostics.title', '维护诊断')}</h2>
        <p className="mt-1.5 text-sm leading-6 text-[hsl(var(--memory-body))]">{label('diagnostics.subtitle', '把需要运维注意的记忆问题集中在这里。')}</p>
      </div>
      <div className="space-y-1">
        {diagnostics.map((item) => (
          <div key={item.id} className="flex items-start gap-3 rounded-lg px-3 py-3 transition-colors duration-200 hover:bg-[hsl(var(--memory-panel-subtle)/0.5)]">
            {item.severity === 'ok' ? <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-600" /> : <AlertTriangle className={cn('mt-0.5 h-5 w-5', item.severity === 'danger' ? 'text-red-600' : 'text-amber-600')} />}
            <div className="min-w-0">
              <div className="font-semibold text-[hsl(var(--memory-title))]">{item.title}</div>
              <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">{item.detail}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
