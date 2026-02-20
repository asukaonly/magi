import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export function LoadingSpinner({ className }: { className?: string }): JSX.Element {
  return <Loader2 className={cn('h-5 w-5 animate-spin text-primary', className)} />;
}
