import React from 'react';
import { CheckCircle2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { ONBOARDING_DESCRIPTION_CLASS, ONBOARDING_TITLE_CLASS } from './onboardingStyles';

interface CompletionScreenProps {
  connectedSourceCount?: number;
}

export const CompletionScreen: React.FC<CompletionScreenProps> = ({
  connectedSourceCount = 0,
}) => {
  const { t } = useTranslation('onboarding');
  const hasConnectedSources = connectedSourceCount > 0;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="w-full max-w-3xl">
        <h1 className={ONBOARDING_TITLE_CLASS}>{t('messages.completedTitle')}</h1>
        <p className={ONBOARDING_DESCRIPTION_CLASS}>{t('messages.completedDesc')}</p>
        <div className="mt-6 flex items-start gap-3 rounded-xl bg-muted/45 p-5">
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
          <p className="text-sm leading-6 text-muted-foreground">
            {hasConnectedSources
              ? t('messages.completedNoteWithSources')
              : t('messages.completedNoteNoSources')}
          </p>
        </div>
      </div>
    </div>
  );
};

export default CompletionScreen;
