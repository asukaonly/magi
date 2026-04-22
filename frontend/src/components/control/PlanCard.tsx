/**
 * Card that renders the current plan-mode state for a session.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { getPlanState, PlanStateDTO } from '@/api/modules/control';
import { useControlEvents } from '@/realtime/useControlEvents';

export interface PlanCardProps {
  sessionId: string | null | undefined;
  intervalMs?: number;
}

export function PlanCard({ sessionId, intervalMs = 10000 }: PlanCardProps) {
  const { t } = useTranslation('control');
  const [state, setState] = useState<PlanStateDTO | null>(null);

  const pull = useCallback(async () => {
    if (!sessionId) {
      setState(null);
      return;
    }
    try {
      const next = await getPlanState(sessionId);
      setState(next);
    } catch {
      // ignore
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) {
      setState(null);
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
    onPlanUpdated: () => {
      void pull();
    },
  });

  if (!state) return null;

  return (
    <Card data-testid="plan-card">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">
          {state.active ? t('plan.badge_active') : t('plan.badge_inactive')}
        </CardTitle>
        <Badge variant={state.active ? 'default' : 'secondary'}>
          {state.active ? t('plan.entered') : t('plan.exited')}
        </Badge>
      </CardHeader>
      <CardContent>
        {state.plan_text ? (
          <pre className="whitespace-pre-wrap text-sm leading-relaxed">
            {state.plan_text}
          </pre>
        ) : (
          <div className="text-sm text-muted-foreground">
            {t('plan.empty')}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
