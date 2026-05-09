import { Check, ChevronDown, FolderOpen, RotateCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
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
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                data-testid="chat-workspace-trigger"
                disabled={updatingWorkspace}
                aria-label={t('chat.workspace.recentMenu')}
                title={workspaceDisplayPath}
                className="group flex min-w-0 max-w-[min(58vw,38rem)] items-center gap-2 rounded-full bg-background/96 px-3.5 py-2 text-left text-sm text-foreground/78 transition-colors hover:bg-background hover:text-foreground/92 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20 focus-visible:ring-offset-2 focus-visible:ring-offset-background data-[state=open]:bg-background data-[state=open]:text-foreground disabled:pointer-events-none disabled:opacity-60"
              >
                <span
                  data-testid="chat-workspace-path"
                  aria-label={t('chat.workspace.label')}
                  className="min-w-0 flex-1 truncate"
                  title={workspaceDisplayPath}
                >
                  {workspaceDisplayPath}
                </span>
                <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground/72 group-data-[state=open]:text-foreground/72" />
                <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-all group-hover:text-foreground/72 group-data-[state=open]:rotate-180 group-data-[state=open]:text-foreground/72" />
              </button>
            </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-[min(28rem,80vw)] rounded-2xl border-border/70 bg-background/98 p-2 shadow-[0_18px_50px_rgba(15,23,42,0.14)] backdrop-blur">
                <div className="px-2 py-1 text-xs font-medium text-muted-foreground">
                  {t('chat.workspace.recentTitle')}
                </div>
                <DropdownMenuItem onSelect={onChangeWorkspace} className="rounded-xl px-3 py-2.5">
                  <FolderOpen className="h-4 w-4" />
                  {t('settings.actions.chooseDirectory')}
                </DropdownMenuItem>
                {hasSessionWorkspaceOverride && (
                  <DropdownMenuItem onSelect={onClearWorkspace} className="rounded-xl px-3 py-2.5">
                    <RotateCcw className="h-4 w-4" />
                    {t('settings.actions.restoreDefaultDirectory')}
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator className="bg-border/60" />
                {recentWorkspaces.length > 0 ? recentWorkspaces.map((workspacePath) => {
                  const isCurrent = normalizedCurrentWorkspace.length > 0
                    && workspacePath === normalizedCurrentWorkspace;

                  return (
                    <DropdownMenuItem
                      key={workspacePath}
                      onSelect={() => onSelectWorkspace(workspacePath)}
                      className="rounded-xl px-3 py-2.5 pr-3"
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
  );
};