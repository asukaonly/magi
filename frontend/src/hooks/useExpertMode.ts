import { useCallback, useEffect, useRef, useState } from 'react';
import { configApi } from '@/api';
import { APP_EVENTS, subscribeToAppEvent } from '@/constants/events';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';

/** Operator tools require a confirmed expert preference from the active center. */
export function useExpertMode(): boolean | null {
  const [expert, setExpert] = useState<boolean | null>(null);
  const revision = useRef(0);
  const refresh = useCallback(async () => {
    const request = ++revision.current;
    setExpert(null);
    try {
      const response = await configApi.get();
      if (request === revision.current) setExpert(response.data?.preferences.user_mode === 'expert');
    } catch {
      if (request === revision.current) setExpert(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const unsubscribe = subscribeToAppEvent(APP_EVENTS.SETTINGS_SAVED, () => { void refresh(); });
    return () => { revision.current += 1; unsubscribe(); };
  }, [refresh]);
  useCenterRefresh(refresh, ['config']);
  return expert;
}
