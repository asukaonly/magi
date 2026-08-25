import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { messagesApi } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import { normalizeTraceSnapshot } from '@/domain/chat/state';
import { useChatTraceStore } from '@/stores';

const USER_ID = DEFAULT_USER_ID;

type UseChatTraceDrawerOptions = {
  currentSessionId: string | null;
};

export function useChatTraceDrawer({ currentSessionId }: UseChatTraceDrawerOptions) {
  const { t } = useTranslation('app');
  const summaries = useChatTraceStore((state) => state.summaries);
  const snapshots = useChatTraceStore((state) => state.snapshots);
  const drawerOpen = useChatTraceStore((state) => state.drawerOpen);
  const activeTurnId = useChatTraceStore((state) => state.activeTurnId);
  const setSnapshot = useChatTraceStore((state) => state.setSnapshot);
  const openDrawer = useChatTraceStore((state) => state.openDrawer);
  const closeDrawer = useChatTraceStore((state) => state.closeDrawer);
  const resetTraceDrawer = useChatTraceStore((state) => state.reset);
  const [loadingTrace, setLoadingTrace] = useState(false);

  const loadTrace = useCallback(async (turnId: string) => {
    if (!currentSessionId || !turnId) return;
    setLoadingTrace(true);
    try {
      const result = await messagesApi.getTrace(USER_ID, currentSessionId, turnId);
      const snapshot = normalizeTraceSnapshot(result.trace || undefined);
      if (snapshot) {
        setSnapshot(result.trace!);
      } else {
        console.warn('[chat.trace] Trace response did not contain a valid snapshot', {
          sessionId: currentSessionId,
          turnId,
          responseSuccess: result.success,
          responseTurnId: result.turn_id,
        });
      }
    } catch (error) {
      console.error('[chat.trace] Failed to load trace snapshot', {
        sessionId: currentSessionId,
        turnId,
        error,
      });
      toast.error(t('chat.trace.loadFailed'));
    } finally {
      setLoadingTrace(false);
    }
  }, [currentSessionId, setSnapshot, t]);

  const refreshVisibleTrace = useCallback((turnId: string) => {
    const normalizedTurnId = String(turnId || '').trim();
    if (!normalizedTurnId) return;
    if (drawerOpen && activeTurnId === normalizedTurnId) {
      void loadTrace(normalizedTurnId);
    }
  }, [activeTurnId, drawerOpen, loadTrace]);

  const openTraceDrawer = useCallback((turnId: string) => {
    const normalizedTurnId = String(turnId || '').trim();
    if (!normalizedTurnId) return;
    window.setTimeout(() => {
      openDrawer(normalizedTurnId);
      void loadTrace(normalizedTurnId);
    }, 0);
  }, [loadTrace, openDrawer]);

  return {
    loadingTrace,
    summaries,
    snapshots,
    drawerOpen,
    activeTurnId,
    openTraceDrawer,
    closeTraceDrawer: closeDrawer,
    refreshVisibleTrace,
    resetTraceDrawer,
  };
}
