/**
 * Card that renders the current plan-mode state for a session.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { getPlanState, PlanStateDTO } from '@/api/modules/control';

export interface PlanCardProps {
  sessionId: string | null | undefined;
  intervalMs?: number;
}

export function PlanCard({ sessionId, intervalMs = 2000 }: PlanCardProps) {
  const { t } = useTranslation('control');
  const [state, setState] = useState<PlanStateDTO | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setState(null);
      return;
    }
    let cancelled = false;
    const pull = async () => {
      try {
        const next = await getPlanState(sessionId);
        if (!cancelled) setState(next);
      } catch {
        // ignore
      }
    };
    void pull();
    if (intervalMs <= 0) return () => undefined;
    const handle = setInterval(pull, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, [sessionId, intervalMs]);

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
