import { useCallback, useState } from 'react';
import { toast } from 'sonner';
import { messagesApi } from '@/api';
import type { ChatSessionListItem } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import { APP_EVENTS } from '@/constants/events';
import { pickDirectory } from '@/runtime/desktop';

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

  const persistSessionWorkspace = useCallback(async (workspacePath: string | null) => {
    if (!currentSessionId) {
      toast.error(translate('chat.sessionRequired'));
      return;
    }

    setUpdatingWorkspace(true);
    try {
      const response = await messagesApi.updateSessionWorkspace(USER_ID, currentSessionId, workspacePath);
      upsertSession(response.session);
      window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      toast.error(translate('chat.workspace.updateFailed', { message }));
    } finally {
      setUpdatingWorkspace(false);
    }
  }, [currentSessionId, translate, upsertSession]);

  const handlePickWorkspace = useCallback(async () => {
    const selectedPath = await pickDirectory(currentWorkspacePath ?? null);
    if (!selectedPath) {
      return;
    }

    await persistSessionWorkspace(selectedPath);
  }, [currentWorkspacePath, persistSessionWorkspace]);

  return {
    updatingWorkspace,
    persistSessionWorkspace,
    handlePickWorkspace,
  };
}