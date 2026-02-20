import React from 'react';
import { CheckCircle2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';

interface CompletionScreenProps {
  onFinish: () => void;
}

export const CompletionScreen: React.FC<CompletionScreenProps> = ({ onFinish }) => {
  const { t } = useTranslation('onboarding');

  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 py-10 text-center">
        <CheckCircle2 className="h-12 w-12 text-emerald-600" />
        <div>
          <h3 className="text-lg font-semibold">{t('messages.completedTitle')}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{t('messages.completedDesc')}</p>
        </div>
        <Button onClick={onFinish}>{t('actions.enterApp')}</Button>
      </CardContent>
    </Card>
  );
};

export default CompletionScreen;
