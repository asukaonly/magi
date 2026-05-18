import React, { createContext, useCallback, useContext, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useConversationStore } from '@/stores';
import { useChatWorkspaceActions } from '@/hooks/useChatWorkspaceActions';

/**
 * Single-flight workspace state for the chat shell.
 *
 * The picker used to live inside the chat page. Now both AppTitleBar and
 * Chat.tsx need the same handlers; calling `useChatWorkspaceActions` from
 * two places would double-fetch `recentWorkspaces`. The provider here
 * calls the hook once at the layout root and shares the result via
 * context.
 */

type ChatWorkspaceContextValue = {
  currentWorkspacePath: string | null;
  workspaceDisplayPath: string;
  hasSessionWorkspaceOverride: boolean;
  recentWorkspaces: string[];
  updatingWorkspace: boolean;
  onChangeWorkspace: () => void;
  onSelectWorkspace: (workspacePath: string) => void;
  onClearWorkspace: () => void;
};

const ChatWorkspaceContext = createContext<ChatWorkspaceContextValue | null>(null);

const DEFAULT_CHAT_WORKSPACE_DISPLAY = '~/.magi/chat-workspace';

const getWorkspaceDisplayPath = (workspacePath: string | null | undefined): string => {
  const trimmed = String(workspacePath || '').trim();
  if (!trimmed) {
    return DEFAULT_CHAT_WORKSPACE_DISPLAY;
  }
  return trimmed;
};

export const ChatWorkspaceProvider = ({ children }: { children: React.ReactNode }) => {
  const { t } = useTranslation('app');
  const currentSessionId = useConversationStore((s) => s.currentSessionId);
  const currentSession = useConversationStore((s) =>
    s.currentSessionId ? s.sessionsById[s.currentSessionId] : null,
  );
  const upsertSession = useConversationStore((s) => s.upsertSession);

  const {
    recentWorkspaces,
    updatingWorkspace,
    persistSessionWorkspace,
    handlePickWorkspace,
    handleSelectRecentWorkspace,
  } = useChatWorkspaceActions({
    currentSessionId,
    currentWorkspacePath: currentSession?.workspace_path,
    upsertSession,
    translate: t,
  });

  const onChangeWorkspace = useCallback(() => {
    void handlePickWorkspace();
  }, [handlePickWorkspace]);

  const onSelectWorkspace = useCallback(
    (workspacePath: string) => {
      void handleSelectRecentWorkspace(workspacePath);
    },
    [handleSelectRecentWorkspace],
  );

  const onClearWorkspace = useCallback(() => {
    void persistSessionWorkspace(null);
  }, [persistSessionWorkspace]);

  const value = useMemo<ChatWorkspaceContextValue>(
    () => ({
      currentWorkspacePath: currentSession?.workspace_path ?? null,
      workspaceDisplayPath: getWorkspaceDisplayPath(currentSession?.workspace_path),
      hasSessionWorkspaceOverride: Boolean(String(currentSession?.workspace_path || '').trim()),
      recentWorkspaces,
      updatingWorkspace,
      onChangeWorkspace,
      onSelectWorkspace,
      onClearWorkspace,
    }),
    [
      currentSession?.workspace_path,
      recentWorkspaces,
      updatingWorkspace,
      onChangeWorkspace,
      onSelectWorkspace,
      onClearWorkspace,
    ],
  );

  return (
    <ChatWorkspaceContext.Provider value={value}>{children}</ChatWorkspaceContext.Provider>
  );
};

export function useChatWorkspaceContext(): ChatWorkspaceContextValue | null {
  return useContext(ChatWorkspaceContext);
}
