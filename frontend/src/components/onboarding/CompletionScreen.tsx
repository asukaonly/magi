import React from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { EmptyStateAvailableSensors } from '@/components/empty-state/EmptyStateAvailableSensors';
import type { InstallableItem } from '@/api/modules/systemSuggestions';

interface CompletionScreenProps {
  onFinish: () => void;
  loading?: boolean;
  loadingLabel?: string;
  installableItems?: InstallableItem[];
  installableLoading?: boolean;
}

export const CompletionScreen: React.FC<CompletionScreenProps> = ({
  onFinish,
  loading = false,
  loadingLabel,
  installableItems,
  installableLoading,
}) => {
  const { t } = useTranslation('onboarding');

  return (
    <div className="h-full min-h-0 overflow-y-auto">
      <Card>
        <CardContent className="px-8 py-10">
          <div className="flex flex-col items-center gap-4 text-center">
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
          </div>

          <div className="mx-auto mt-8 w-full max-w-3xl border-t border-border/60 pt-6">
            <EmptyStateAvailableSensors
              showBrowseAll={false}
              fallbackPluginIds={['chrome-history', 'git-activity']}
              installableItems={installableItems}
              installableLoading={installableLoading}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default CompletionScreen;
