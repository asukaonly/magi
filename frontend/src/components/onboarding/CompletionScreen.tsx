import React from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';

interface CompletionScreenProps {
  onFinish: () => void;
  connectedSourceCount?: number;
  loading?: boolean;
  loadingLabel?: string;
}

export const CompletionScreen: React.FC<CompletionScreenProps> = ({
  onFinish,
  connectedSourceCount = 0,
  loading = false,
  loadingLabel,
}) => {
  const { t } = useTranslation('onboarding');
  const hasConnectedSources = connectedSourceCount > 0;

  return (
    <div className="h-full min-h-0 overflow-y-auto">
      <Card>
        <CardContent className="px-8 py-10">
          <div className="flex flex-col items-center gap-5 text-center">
            <CheckCircle2 className="h-12 w-12 text-emerald-600" />
            <div>
              <h3 className="text-lg font-semibold">{t('messages.completedTitle')}</h3>
              <p className="mt-1 max-w-md text-sm leading-6 text-muted-foreground">
                {t('messages.completedDesc')}
              </p>
            </div>
            <div className="w-full max-w-md rounded-lg border border-border/60 bg-muted/20 px-4 py-3 text-left text-sm leading-6 text-muted-foreground">
              <p>
                {hasConnectedSources
                  ? t('messages.completedStepBackground')
                  : t('messages.completedStepNoSources')}
              </p>
              <p>
                {hasConnectedSources
                  ? t('messages.completedStepBackfillWithSources')
                  : t('messages.completedStepBackfillNoSources')}
              </p>
            </div>
            <Button onClick={onFinish} disabled={loading}>
              {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {loading ? loadingLabel || t('actions.saving') : t('actions.enterApp')}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default CompletionScreen;
