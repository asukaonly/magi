import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type PropsWithChildren,
} from 'react';
import { getRuntimeConfig } from '@/runtime/config';
import { useRealtimeStore } from '@/stores/realtime-store';
import { RealtimeClient, type RealtimeMessage } from './client';

type RealtimeContextValue = {
  send: (message: Record<string, unknown>) => void;
  subscribe: (listener: (message: RealtimeMessage) => void) => () => void;
};

const USER_CHANNEL = 'user_web_user';

const RealtimeContext = createContext<RealtimeContextValue | null>(null);

const resolveWsUrl = (): string => {
  const runtime = getRuntimeConfig();
  const base = `${runtime.wsBaseUrl}/ws`;
  if (!runtime.sessionToken) {
    return base;
  }
  const separator = base.includes('?') ? '&' : '?';
  return `${base}${separator}token=${encodeURIComponent(runtime.sessionToken)}`;
};

export const RealtimeProvider = ({ children }: PropsWithChildren) => {
  const clientRef = useRef<RealtimeClient>();
  const setConnected = useRealtimeStore((state) => state.setConnected);
  const setLastError = useRealtimeStore((state) => state.setLastError);
  const setReconnectAttempts = useRealtimeStore((state) => state.setReconnectAttempts);
  const resetRealtime = useRealtimeStore((state) => state.reset);

  if (!clientRef.current) {
    clientRef.current = new RealtimeClient();
  }

  useEffect(() => {
    const client = clientRef.current!;
    const unsubscribeStatus = client.subscribeStatus((status) => {
      setConnected(status.connected);
      setLastError(status.lastError);
      setReconnectAttempts(status.reconnectAttempts);
      if (status.connected) {
        client.send({ type: 'subscribe', channel: USER_CHANNEL });
      }
    });

    client.connect(resolveWsUrl());

    return () => {
      unsubscribeStatus();
      client.disconnect();
      resetRealtime();
    };
  }, [resetRealtime, setConnected, setLastError, setReconnectAttempts]);

  const value = useMemo<RealtimeContextValue>(() => ({
    send: (message) => clientRef.current?.send(message),
    subscribe: (listener) => clientRef.current?.subscribe(listener) || (() => undefined),
  }), []);

  return (
    <RealtimeContext.Provider value={value}>
      {children}
    </RealtimeContext.Provider>
  );
};

export const useRealtime = (): RealtimeContextValue => {
  const context = useContext(RealtimeContext);
  if (!context) {
    throw new Error('useRealtime must be used within RealtimeProvider');
  }
  return context;
};
