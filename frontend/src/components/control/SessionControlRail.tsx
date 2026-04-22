/**
 * Compact rail that surfaces per-session control-plane state
 * (plan + todos) inside the chat view. Collapsible and self-hiding
 * when the underlying state has nothing interesting to show.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronUp, ListTodo } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PlanCard } from './PlanCard';
import { TodoPanel } from './TodoPanel';
import {
  getPlanState,
  getTodos,
  PlanStateDTO,
  TodoItemDTO,
} from '@/api/modules/control';
import { useControlEvents } from '@/realtime/useControlEvents';

export interface SessionControlRailProps {
  sessionId: string | null | undefined;
}

/**
 * Watches plan + todo state to decide whether to render the rail at all.
 * Hides itself when there is no plan content and no todos so the chat
 * surface stays clean by default.
 */
export function SessionControlRail({ sessionId }: SessionControlRailProps) {
  const { t } = useTranslation('control');
  const [plan, setPlan] = useState<PlanStateDTO | null>(null);
  const [todos, setTodos] = useState<TodoItemDTO[]>([]);
  const [collapsed, setCollapsed] = useState(false);

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setPlan(null);
      setTodos([]);
      return;
    }
    try {
      const [planState, todoList] = await Promise.all([
        getPlanState(sessionId).catch(() => null),
        getTodos(sessionId).catch(() => [] as TodoItemDTO[]),
      ]);
      setPlan(planState);
      setTodos(todoList);
    } catch {
      // ignore
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
    if (!sessionId) return () => undefined;
    const handle = setInterval(() => {
      void refresh();
    }, 15000);
    return () => {
      clearInterval(handle);
    };
  }, [sessionId, refresh]);

  useControlEvents({
    sessionId: sessionId ?? null,
    onPlanUpdated: () => {
      void refresh();
    },
    onTodoUpdated: () => {
      void refresh();
    },
  });

  if (!sessionId) return null;

  const hasPlan = Boolean(plan && (plan.active || (plan.plan_text ?? '').trim()));
  const hasTodos = todos.length > 0;
  if (!hasPlan && !hasTodos) return null;

  return (
    <div
      data-testid="session-control-rail"
      className="pointer-events-auto absolute right-4 top-16 z-20 flex w-80 max-w-[22rem] flex-col gap-2"
    >
      <div className="flex items-center justify-between rounded-md bg-background/80 px-3 py-1.5 text-xs text-muted-foreground shadow-sm backdrop-blur">
        <span className="inline-flex items-center gap-1.5 font-medium text-foreground/80">
          <ListTodo className="h-3.5 w-3.5" />
          {t('rail.title', { defaultValue: 'Session control' })}
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-2"
          onClick={() => setCollapsed((prev) => !prev)}
          aria-label={collapsed ? 'expand' : 'collapse'}
        >
          {collapsed ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronUp className="h-3.5 w-3.5" />
          )}
        </Button>
      </div>
      {!collapsed && (
        <div className="max-h-[calc(100vh-12rem)] overflow-y-auto rounded-md">
          <div className="space-y-2">
            {hasPlan && <PlanCard sessionId={sessionId} intervalMs={0} />}
            {hasTodos && <TodoPanel sessionId={sessionId} intervalMs={0} />}
          </div>
        </div>
      )}
    </div>
  );
}
