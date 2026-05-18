import { Check, ChevronDown, FolderOpen, RotateCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useChatWorkspaceContext } from '@/stores/chat-workspace-context';

/**
 * Workspace selector. Lives in the AppTitleBar right slot when on the
 * chat route. Reads everything from ChatWorkspaceContext so we don't
 * duplicate the underlying API fetch.
 */
export const ChatWorkspacePicker = () => {
  const { t } = useTranslation('app');
  const ctx = useChatWorkspaceContext();
  if (!ctx) {
    return null;
  }
  const {
    workspaceDisplayPath,
    currentWorkspacePath,
    recentWorkspaces,
    hasSessionWorkspaceOverride,
    updatingWorkspace,
    onChangeWorkspace,
    onSelectWorkspace,
    onClearWorkspace,
  } = ctx;

  const normalizedCurrent = String(currentWorkspacePath || '').trim();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          data-testid="chat-workspace-trigger"
          data-tauri-drag-region="false"
          disabled={updatingWorkspace}
          aria-label={t('chat.workspace.recentMenu')}
          title={workspaceDisplayPath}
          className="group flex h-7 min-w-0 max-w-[min(40vw,28rem)] items-center gap-1.5 rounded-md px-2.5 text-[12.5px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20 data-[state=open]:bg-muted data-[state=open]:text-foreground disabled:pointer-events-none disabled:opacity-60"
        >
          <span
            data-testid="chat-workspace-path"
            aria-label={t('chat.workspace.label')}
            className="min-w-0 flex-1 truncate font-mono text-[11px]"
            title={workspaceDisplayPath}
          >
            {workspaceDisplayPath}
          </span>
          <FolderOpen className="h-3.5 w-3.5 shrink-0 opacity-70 transition-opacity group-hover:opacity-100" />
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60 transition-all group-data-[state=open]:rotate-180" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-[min(28rem,80vw)] rounded-2xl border-border/70 bg-background/98 p-2 shadow-[0_18px_50px_rgba(15,23,42,0.14)] backdrop-blur"
      >
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
        {recentWorkspaces.length > 0 ? (
          recentWorkspaces.map((workspacePath) => {
            const isCurrent = normalizedCurrent.length > 0 && workspacePath === normalizedCurrent;
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
          })
        ) : (
          <div className="px-2 py-1.5 text-sm text-muted-foreground">
            {t('chat.workspace.noRecentDirectories')}
          </div>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
