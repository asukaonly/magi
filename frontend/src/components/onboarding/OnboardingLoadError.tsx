import { AlertTriangle, RefreshCw } from 'lucide-react';
import type React from 'react';

import { Button } from '@/components/ui/button';

interface OnboardingLoadErrorProps {
  title: string;
  description: string;
  retryLabel: string;
  onRetry: () => void;
}

const OnboardingLoadError: React.FC<OnboardingLoadErrorProps> = ({
  title,
  description,
  retryLabel,
  onRetry,
}) => (
  <div className="flex min-h-screen items-center justify-center bg-background px-6 py-12">
    <div
      role="alert"
      className="flex w-full max-w-md flex-col items-center rounded-3xl border border-border/60 bg-card px-8 py-10 text-center shadow-sm"
    >
      <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
        <AlertTriangle aria-hidden="true" className="h-6 w-6" />
      </div>
      <h1 className="text-xl font-semibold text-foreground">{title}</h1>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">{description}</p>
      <Button className="mt-7" type="button" onClick={onRetry}>
        <RefreshCw aria-hidden="true" className="h-4 w-4" />
        {retryLabel}
      </Button>
    </div>
  </div>
);

export default OnboardingLoadError;
