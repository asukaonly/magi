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
      className="inline-flex items-center text-[11px] font-medium text-muted-foreground/55 transition-colors hover:text-muted-foreground"
    >
      {t('chat.reply.action')}
    </button>
  );
};