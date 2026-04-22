/**
 * Side panel that lists the current session's todo items.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { getTodos, TodoItemDTO, TodoStatus } from '@/api/modules/control';
import { useControlEvents } from '@/realtime/useControlEvents';

export interface TodoPanelProps {
  sessionId: string | null | undefined;
  intervalMs?: number;
}

const statusIcons: Record<TodoStatus, string> = {
  not_started: '○',
  in_progress: '◐',
  completed: '●',
};

export function TodoPanel({ sessionId, intervalMs = 10000 }: TodoPanelProps) {
  const { t } = useTranslation('control');
  const [items, setItems] = useState<TodoItemDTO[]>([]);

  const pull = useCallback(async () => {
    if (!sessionId) {
      setItems([]);
      return;
    }
    try {
      const next = await getTodos(sessionId);
      setItems(next);
    } catch {
      // ignore
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) {
      setItems([]);
      return;
    }
    void pull();
    if (intervalMs <= 0) return () => undefined;
    const handle = setInterval(() => {
      void pull();
    }, intervalMs);
    return () => {
      clearInterval(handle);
    };
  }, [sessionId, intervalMs, pull]);

  useControlEvents({
    sessionId: sessionId ?? null,
    onTodoUpdated: () => {
      void pull();
    },
  });

  return (
    <Card data-testid="todo-panel">
      <CardHeader>
        <CardTitle className="text-base">{t('todo.title')}</CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <div className="text-sm text-muted-foreground">{t('todo.empty')}</div>
        ) : (
          <ul className="space-y-2">
            {items.map((item) => (
              <li
                key={item.id}
                className={`flex items-start gap-2 text-sm ${
                  item.status === 'completed'
                    ? 'text-muted-foreground line-through'
                    : ''
                }`}
                data-testid={`todo-${item.id}`}
              >
                <span className="shrink-0 font-mono">
                  {statusIcons[item.status]}
                </span>
                <span className="flex-1">{item.content}</span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {t(`todo.status.${item.status}`)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
