import { Check, ChevronDown, FolderOpen, RotateCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

type ChatWorkspaceStatusBarProps = {
  visible: boolean;
  messageCount: number;
  workspaceDisplayPath: string;
  currentWorkspacePath: string | null;
  recentWorkspaces: string[];
  hasSessionWorkspaceOverride: boolean;
  updatingWorkspace: boolean;
  onChangeWorkspace: () => void;
  onSelectWorkspace: (workspacePath: string) => void;
  onClearWorkspace: () => void;
};

export const ChatWorkspaceStatusBar = ({
  visible,
  messageCount,
  workspaceDisplayPath,
  currentWorkspacePath,
  recentWorkspaces,
  hasSessionWorkspaceOverride,
  updatingWorkspace,
  onChangeWorkspace,
  onSelectWorkspace,
  onClearWorkspace,
}: ChatWorkspaceStatusBarProps) => {
  const { t } = useTranslation('app');
  const normalizedCurrentWorkspace = String(currentWorkspacePath || '').trim();

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
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onChangeWorkspace}
            disabled={updatingWorkspace}
            aria-label={t('chat.workspace.change')}
            title={t('chat.workspace.change')}
            className="h-8 w-8 rounded-full text-muted-foreground hover:bg-muted/50 hover:text-foreground"
          >
            <FolderOpen className="h-4 w-4" />
          </Button>
          <div className="flex min-w-0 items-center rounded-full border border-border/70 bg-background/75 pl-3 pr-1 shadow-sm">
            <span
              data-testid="chat-workspace-path"
              aria-label={t('chat.workspace.label')}
              className="max-w-[min(50vw,32rem)] truncate text-sm text-foreground/75"
              title={workspaceDisplayPath}
            >
              {workspaceDisplayPath}
            </span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={updatingWorkspace}
                  aria-label={t('chat.workspace.recentMenu')}
                  title={t('chat.workspace.recentMenu')}
                  className="ml-1 h-7 w-7 rounded-full text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                >
                  <ChevronDown className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-[min(28rem,80vw)] p-1.5">
                <div className="px-2 py-1 text-xs font-medium text-muted-foreground">
                  {t('chat.workspace.recentTitle')}
                </div>
                <DropdownMenuItem onSelect={onChangeWorkspace}>
                  <FolderOpen className="h-4 w-4" />
                  {t('settings.actions.chooseDirectory')}
                </DropdownMenuItem>
                {hasSessionWorkspaceOverride && (
                  <DropdownMenuItem onSelect={onClearWorkspace}>
                    <RotateCcw className="h-4 w-4" />
                    {t('settings.actions.restoreDefaultDirectory')}
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                {recentWorkspaces.length > 0 ? recentWorkspaces.map((workspacePath) => {
                  const isCurrent = normalizedCurrentWorkspace.length > 0
                    && workspacePath === normalizedCurrentWorkspace;

                  return (
                    <DropdownMenuItem
                      key={workspacePath}
                      onSelect={() => onSelectWorkspace(workspacePath)}
                      className="pr-3"
                    >
                      <Check className={`h-4 w-4 ${isCurrent ? 'opacity-100' : 'opacity-0'}`} />
                      <span className="min-w-0 flex-1 truncate" title={workspacePath}>
                        {workspacePath}
                      </span>
                    </DropdownMenuItem>
                  );
                }) : (
                  <div className="px-2 py-1.5 text-sm text-muted-foreground">
                    {t('chat.workspace.noRecentDirectories')}
                  </div>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>
    </div>
  );
};