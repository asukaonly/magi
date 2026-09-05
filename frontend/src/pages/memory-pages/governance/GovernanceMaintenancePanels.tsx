import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { AlertTriangle, ArrowUpRight, CheckCircle2, Loader2, Play, RefreshCw } from 'lucide-react';
import { memoryApi, type MemoryMaintenanceTask, type EpisodeReconsolidateResult } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export function TaskMaintenancePanel({
  label,
}: {
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
}) {
  const [tasks, setTasks] = useState<MemoryMaintenanceTask[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      setLoading(true);
      try {
        const result = await memoryApi.getMaintenanceTasks();
        if (!active) return;
        setTasks(result.tasks);
        setLoadFailed(false);
      } catch {
        if (!active) return;
        setTasks(null);
        setLoadFailed(true);
      } finally {
        if (active) {
          setLoading(false);
          timer = setTimeout(() => void load(), 30_000);
        }
      }
    };
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [refreshVersion]);

  const rows = [
    ['events', label('tasks.eventsTitle', '原始事件清理'), label('tasks.eventsBody', '压缩可清理事件、清除过期负载')],
    ['structure', label('tasks.structureTitle', '结构维护'), label('tasks.structureBody', '维护实体、断言、关系和纠错派生任务')],
    ['chapter', label('tasks.chapterTitle', '章节整理'), label('tasks.chapterBody', '升级章节、经历和缺失总结')],
    ['summary', label('tasks.summaryTitle', '总结维护'), label('tasks.summaryBody', '生成时段总结并清理过期内容')],
    ['skills', label('tasks.skillsTitle', '工具记忆维护'), label('tasks.skillsBody', '维护工具技能和失败保护状态')],
  ];
  const statuses: Record<string, string> = {
    enabled: label('tasks.availability.enabled', '已启用'),
    disabled: label('tasks.availability.disabled', '已停用'),
    paused: label('tasks.availability.paused', '已暂停'),
    partial: label('tasks.availability.partial', '部分可用'),
    unavailable: label('tasks.availability.unavailable', '不可用'),
    unknown: label('tasks.availability.unknown', '状态未知'),
    loading: label('tasks.availability.loading', '正在读取'),
  };
  const results: Record<string, string> = {
    success: label('tasks.results.success', '最近执行成功'),
    failed: label('tasks.results.failed', '最近执行失败'),
    running: label('tasks.results.running', '正在执行'),
    cancelled: label('tasks.results.cancelled', '最近执行已取消'),
    skipped: label('tasks.results.skipped', '最近执行已跳过'),
    pending: label('tasks.results.pending', '等待执行'),
  };
  return (
    <section className="rounded-xl bg-[hsl(var(--memory-panel-elevated)/0.74)] p-2">
      <div className="flex flex-col gap-3 px-3 pb-4 pt-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-[-0.02em] text-[hsl(var(--memory-title))]">{label('tasks.title', '记忆维护任务')}</h2>
          <p className="mt-1.5 text-sm leading-6 text-[hsl(var(--memory-body))]">{label('tasks.subtitle', '状态来自当前功能开关和调度运行情况，每 30 秒刷新。')}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="ghost" size="sm" disabled={loading} onClick={() => setRefreshVersion((value) => value + 1)}>
            <RefreshCw aria-hidden="true" className={cn('mr-1.5 h-4 w-4', loading && 'animate-spin')} />
            {label('tasks.refresh', '刷新状态')}
          </Button>
          <Link to="/tasks/schedules" className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm font-medium text-[hsl(var(--memory-accent))] transition-colors duration-200 hover:bg-[hsl(var(--memory-accent-soft)/0.46)] hover:text-[hsl(var(--memory-title))]">
            {label('tasks.openSchedules', '打开调度配置')}
            <ArrowUpRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
      {loadFailed ? <p role="alert" className="px-3 pb-3 text-sm text-destructive">{label('tasks.loadFailed', '无法读取维护任务状态，请重试。')}</p> : null}
      <div className="space-y-1" aria-busy={loading}>
        {rows.map(([id, name, description]) => {
          const task = tasks?.find((item) => item.id === id);
          const status = loading ? 'loading' : task?.status ?? 'unknown';
          return (
            <div key={id} role="group" aria-label={name} className="grid gap-2 rounded-lg px-3 py-3 text-sm transition-colors duration-200 hover:bg-[hsl(var(--memory-panel-subtle)/0.54)] md:grid-cols-[140px_minmax(0,1fr)_110px_170px] md:items-center">
              <div className="font-semibold text-[hsl(var(--memory-title))]">{name}</div>
              <div className="leading-6 text-[hsl(var(--memory-body))]">{description}</div>
              <div className="text-xs text-[hsl(var(--memory-muted))]">
                <span className="inline-flex items-center gap-2">
                  <span aria-hidden="true" className={cn('h-1.5 w-1.5 rounded-full', status === 'enabled' ? 'bg-emerald-500' : status === 'partial' ? 'bg-amber-500' : 'bg-muted-foreground/50')} />
                  {statuses[status] ?? statuses.unknown}
                </span>
                {task && !loading ? <p className="mt-1">{label('tasks.availableCount', '{{enabled}} / {{total}} 项可运行', { enabled: task.enabled_count, total: task.schedule_count })}</p> : null}
              </div>
              <div className="text-xs leading-5 text-[hsl(var(--memory-muted))]">
                {loading || !task ? statuses[status] : task.last_result ? results[task.last_result] ?? statuses.unknown : label('tasks.neverRun', '暂无执行记录')}
                {task?.last_run_at && !loading ? <p>{label('tasks.lastRunAt', '最近执行：{{time}}', { time: new Date(task.last_run_at * 1000).toLocaleString(document.documentElement.lang || undefined) })}</p> : null}
              </div>
            </div>
          );
        })}
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
  onFlushProjectionJobs,
  l2ActionLoading,
}: {
  label: (key: string, defaultValue: string, values?: Record<string, unknown>) => string;
  reconsolidating: boolean;
  reconsolidateResult: EpisodeReconsolidateResult | null;
  reconsolidateError: string | null;
  onReconsolidate: () => Promise<void>;
  onFlushProjectionJobs: () => Promise<void>;
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
        onClick={() => void onFlushProjectionJobs()}
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
