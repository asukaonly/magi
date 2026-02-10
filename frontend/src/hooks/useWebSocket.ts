/**
 * useWebSocket Hook
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import wsClient, { WebSocketClient } from '../utils/websocket';

interface UseWebSocketOptions {
  autoConnect?: boolean;
  onConnected?: (socketId: string) => void;
  onDisconnected?: (reason: string) => void;
  onError?: (error: any) => void;
}

interface WebSocketState {
  connected: boolean;
  socketId: string | undefined;
  error: string | null;
}

export const useWebSocket = (options: UseWebSocketOptions = {}) => {
  const { autoConnect = false, onConnected, onDisconnected, onError } = options;

  const [state, setState] = useState<WebSocketState>({
    connected: false,
    socketId: undefined,
    error: null,
  });

  const handlersRef = useRef<Map<string, (data: any) => void>>(new Map());

  useEffect(() => {
    if (autoConnect) {
      wsClient.connect();
    }

    // 注册事件监听器
    const unsubscribeConnected = wsClient.on('connected', (data) => {
      console.log('Connected:', data);
      setState({
        connected: true,
        socketId: data.socketId,
        error: null,
      });
      onConnected?.(data.socketId);
    });

    const unsubscribeDisconnected = wsClient.on('disconnected', (data) => {
      console.log('Disconnected:', data);
      setState((prev) => ({
        ...prev,
        connected: false,
      }));
      onDisconnected?.(data.reason);
    });

    const unsubscribeError = wsClient.on('error', (data) => {
      console.error('WebSocket error:', data);
      setState((prev) => ({
        ...prev,
        error: data.message || 'Connection error',
      }));
      onError?.(data);
    });

    // 清理函数
    return () => {
      unsubscribeConnected();
      unsubscribeDisconnected();
      unsubscribeError();

      // 清理所有自定义事件监听器
      handlersRef.current.forEach((_, event) => {
        wsClient.off(event, () => {});
      });
      handlersRef.current.clear();
    };
  }, [autoConnect, onConnected, onDisconnected, onError]);

  // 订阅事件
  const subscribe = useCallback((event: string, handler: (data: any) => void) => {
    const unsubscribe = wsClient.on(event, handler);
    handlersRef.current.set(event, handler);
    return unsubscribe;
  }, []);

  // 取消订阅
  const unsubscribe = useCallback((event: string, handler: (data: any) => void) => {
    wsClient.off(event, handler);
    handlersRef.current.delete(event);
  }, []);

  // 发送消息
  const send = useCallback((event: string, data?: any) => {
    wsClient.send(event, data);
  }, []);

  // 订阅频道
  const subscribeChannel = useCallback((channel: string) => {
    wsClient.subscribe(channel);
  }, []);

  // 取消订阅频道
  const unsubscribeChannel = useCallback((channel: string) => {
    wsClient.unsubscribe(channel);
  }, []);

  // Ping
  const ping = useCallback(() => {
    wsClient.ping();
  }, []);

  // 断开连接
  const disconnect = useCallback(() => {
    wsClient.disconnect();
  }, []);

  return {
    ...state,
    subscribe,
    unsubscribe,
    send,
    subscribeChannel,
    unsubscribeChannel,
    ping,
    disconnect,
    isConnected: () => wsClient.isConnected(),
    getId: () => wsClient.getId(),
  };
};

export default useWebSocket;
