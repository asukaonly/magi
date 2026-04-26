import { CornerUpLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';

type ReplyActionButtonProps = {
  onClick: (event: React.MouseEvent<HTMLButtonElement>) => void;
};

export const ReplyActionButton = ({ onClick }: ReplyActionButtonProps) => {
  const { t } = useTranslation();

  return (
    <button
      type="button"
      aria-label={t('chat.reply.action')}
      title={t('chat.reply.action')}
      onClick={onClick}
      className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground transition-colors hover:text-primary"
    >
      <CornerUpLeft className="h-3 w-3" />
      {t('chat.reply.action')}
    </button>
  );
};