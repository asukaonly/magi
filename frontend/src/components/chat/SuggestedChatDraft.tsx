import { useLocation } from 'react-router';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import { useAppNavigate } from '@/hooks/useAppNavigate';
import { Button } from '@/components/ui/button';

const draftSchema = z.object({ suggestedDraft: z.string().min(1).max(5000) });

export function SuggestedChatDraft({ onInsert, disabled }: { onInsert: (text: string) => void; disabled: boolean }) {
  const location = useLocation();
  const navigate = useAppNavigate();
  const { t } = useTranslation('app');
  const parsed = draftSchema.safeParse(location.state);
  if (!parsed.success) return null;
  const clear = () => navigate(location.pathname + location.search, { replace: true, state: null });
  return <div className="mx-6 mb-2 rounded-lg border border-border p-3 text-sm">
    <p className="line-clamp-3 whitespace-pre-wrap">{parsed.data.suggestedDraft}</p>
    <div className="mt-2 flex gap-2"><Button size="sm" disabled={disabled} onClick={() => { onInsert(parsed.data.suggestedDraft); clear(); }}>{t('personality.thoughts.insertDraft')}</Button>
      <Button size="sm" variant="ghost" onClick={clear}>{t('personality.thoughts.cancel')}</Button></div>
  </div>;
}
