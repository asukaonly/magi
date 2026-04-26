import { FolderOpen, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';

type ChatWorkspaceStatusBarProps = {
  visible: boolean;
  messageCount: number;
  workspaceDisplayPath: string;
  hasSessionWorkspaceOverride: boolean;
  updatingWorkspace: boolean;
  onChangeWorkspace: () => void;
  onClearWorkspace: () => void;
};

export const ChatWorkspaceStatusBar = ({
  visible,
  messageCount,
  workspaceDisplayPath,
  hasSessionWorkspaceOverride,
  updatingWorkspace,
  onChangeWorkspace,
  onClearWorkspace,
}: ChatWorkspaceStatusBarProps) => {
  const { t } = useTranslation('app');

  if (!visible) {
    return null;
  }

  return (
    <div className="mb-2 shrink-0 px-2 py-1">
      <div className="flex flex-col gap-2 text-sm text-muted-foreground lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-2">
          <span data-testid="chat-workspace-message-count" className="font-medium text-foreground/80">
            {messageCount}
          </span>
          <span>{t('chat.workspace.messageCount')}</span>
        </div>
        <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
          <span
            data-testid="chat-workspace-path"
            aria-label={t('chat.workspace.label')}
            className="max-w-[min(56vw,36rem)] truncate text-sm text-foreground/75"
            title={workspaceDisplayPath}
          >
            {workspaceDisplayPath}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onChangeWorkspace}
            disabled={updatingWorkspace}
            className="h-8 rounded-full px-2.5 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
          >
            <FolderOpen className="mr-2 h-4 w-4" />
            {t('chat.workspace.change')}
          </Button>
          {hasSessionWorkspaceOverride && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onClearWorkspace}
              disabled={updatingWorkspace}
              className="h-8 rounded-full px-2.5 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            >
              <X className="mr-2 h-4 w-4" />
              {t('chat.workspace.clear')}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};