import React from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { EmptyStateAvailableSensors } from '@/components/empty-state/EmptyStateAvailableSensors';

interface CompletionScreenProps {
  onFinish: () => void;
  loading?: boolean;
  loadingLabel?: string;
}

export const CompletionScreen: React.FC<CompletionScreenProps> = ({
  onFinish,
  loading = false,
  loadingLabel,
}) => {
  const { t } = useTranslation('onboarding');

  return (
    <div className="flex h-full min-h-0 flex-col gap-6 overflow-y-auto">
      <Card className="shrink-0">
        <CardContent className="flex flex-col items-center gap-4 py-10 text-center">
          <CheckCircle2 className="h-12 w-12 text-emerald-600" />
          <div>
            <h3 className="text-lg font-semibold">{t('messages.completedTitle')}</h3>
            <p className="mt-1 max-w-md text-sm leading-6 text-muted-foreground">
              {t('messages.completedDesc')}
            </p>
          </div>
          <Button onClick={onFinish} disabled={loading}>
            {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {loading ? loadingLabel || t('actions.saving') : t('actions.enterApp')}
          </Button>
        </CardContent>
      </Card>

      <div className="mx-auto w-full max-w-3xl">
        <EmptyStateAvailableSensors
          showBrowseAll={false}
          fallbackPluginIds={['chrome-history', 'git-activity']}
        />
      </div>
    </div>
  );
};

export default CompletionScreen;
