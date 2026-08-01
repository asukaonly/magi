import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { messagesApi } from '@/api';
import type { ChatSessionListItem } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import { APP_EVENTS } from '@/constants/events';
import { pickDirectory } from '@/runtime/desktop';
import {
  captureBrowserContentGeneration,
  isBrowserContentGenerationCurrent,
} from '@/lib/browserContentGeneration';

const USER_ID = DEFAULT_USER_ID;

type UseChatWorkspaceActionsOptions = {
  currentSessionId: string | null;
  currentWorkspacePath: string | null | undefined;
  upsertSession: (session: ChatSessionListItem) => void;
  translate: (key: string, options?: Record<string, unknown>) => string;
};

export function useChatWorkspaceActions({
  currentSessionId,
  currentWorkspacePath,
  upsertSession,
  translate,
}: UseChatWorkspaceActionsOptions) {
  const [updatingWorkspace, setUpdatingWorkspace] = useState(false);
  const [recentWorkspaces, setRecentWorkspaces] = useState<string[]>([]);

  const loadRecentWorkspaces = useCallback(async () => {
    const contentGeneration = captureBrowserContentGeneration();
    const operationIsCurrent = () => (
      isBrowserContentGenerationCurrent(contentGeneration)
    );
    try {
      const response = await messagesApi.getRecentWorkspaces();
      if (operationIsCurrent()) {
        setRecentWorkspaces(Array.isArray(response.paths) ? response.paths : []);
      }
    } catch {
      if (operationIsCurrent()) {
        setRecentWorkspaces([]);
      }
    }
  }, []);

  useEffect(() => {
    void loadRecentWorkspaces();
  }, [loadRecentWorkspaces]);

  const persistSessionWorkspace = useCallback(async (
    workspacePath: string | null,
    options?: { remember?: boolean },
  ) => {
    if (!currentSessionId) {
      toast.error(translate('chat.sessionRequired'));
      return;
    }

    const contentGeneration = captureBrowserContentGeneration();
    const operationIsCurrent = () => (
      isBrowserContentGenerationCurrent(contentGeneration)
    );
    setUpdatingWorkspace(true);
    try {
      const response = await messagesApi.updateSessionWorkspace(USER_ID, currentSessionId, workspacePath);
      if (!operationIsCurrent()) {
        return;
      }
      if (workspacePath && options?.remember !== false) {
        const recent = await messagesApi.rememberWorkspace(workspacePath);
        if (!operationIsCurrent()) {
          return;
        }
        setRecentWorkspaces(Array.isArray(recent.paths) ? recent.paths : []);
      }
      if (!operationIsCurrent()) {
        return;
      }
      upsertSession(response.session);
      window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
    } catch (error: unknown) {
      if (operationIsCurrent()) {
        const message = error instanceof Error ? error.message : 'unknown';
        toast.error(translate('chat.workspace.updateFailed', { message }));
      }
    } finally {
      setUpdatingWorkspace(false);
    }
  }, [currentSessionId, translate, upsertSession]);

  const handlePickWorkspace = useCallback(async () => {
    const contentGeneration = captureBrowserContentGeneration();
    const selectedPath = await pickDirectory(currentWorkspacePath ?? recentWorkspaces[0] ?? null);
    if (
      !selectedPath
      || !isBrowserContentGenerationCurrent(contentGeneration)
    ) {
      return;
    }

    await persistSessionWorkspace(selectedPath);
  }, [currentWorkspacePath, persistSessionWorkspace, recentWorkspaces]);

  const handleSelectRecentWorkspace = useCallback(async (workspacePath: string) => {
    await persistSessionWorkspace(workspacePath);
  }, [persistSessionWorkspace]);

  return {
    recentWorkspaces,
    updatingWorkspace,
    persistSessionWorkspace,
    handlePickWorkspace,
    handleSelectRecentWorkspace,
  };
}
