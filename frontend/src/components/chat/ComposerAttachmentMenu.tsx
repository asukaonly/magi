import { FileText, ImagePlus, Paperclip } from 'lucide-react';
import { useTranslation } from 'react-i18next';

type ComposerAttachmentMenuProps = {
  isOpen: boolean;
  coreModelSupportsVision: boolean;
  onToggle: () => void;
  onPickImage: () => void;
  onPickFile: () => void;
  disabled?: boolean;
};

export const ComposerAttachmentMenu = ({
  isOpen,
  coreModelSupportsVision,
  onToggle,
  onPickImage,
  onPickFile,
  disabled = false,
}: ComposerAttachmentMenuProps) => {
  const { t } = useTranslation();

  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        disabled={disabled}
        aria-label={t('chat.attachments.add')}
        title={t('chat.attachments.add')}
        className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent"
      >
        <Paperclip className="h-4 w-4" />
      </button>

      {isOpen && !disabled ? (
        <div className="absolute bottom-full left-0 mb-2 flex w-44 flex-col gap-1 rounded-xl border border-border/60 bg-background p-2 shadow-lg">
          <button
            type="button"
            onClick={onPickImage}
            disabled={!coreModelSupportsVision}
            className="flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-muted/55 disabled:cursor-not-allowed disabled:text-muted-foreground"
          >
            <ImagePlus className="h-4 w-4" />
            {t('chat.attachments.addImage')}
          </button>
          <button
            type="button"
            onClick={onPickFile}
            className="flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-muted/55"
          >
            <FileText className="h-4 w-4" />
            {t('chat.attachments.addFile')}
          </button>
        </div>
      ) : null}
    </div>
  );
};
