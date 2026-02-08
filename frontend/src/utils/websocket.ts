/**
 * WebSocket客户端
 */
import { io, Socket } from 'socket.io-client';

// WebSocket事件类型
export interface WebSocketMessage {
  type: string;
  [key: string]: any;
}

type EventHandler = (data: any) => void;

class WebSocketClient {
  private socket: Socket | null = null;
  private url: string;
  private connected: boolean = false;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 5;
  private reconnectDelay: number = 1000;

  // 事件处理器
  private eventHandlers: Map<string, Set<EventHandler>> = new Map();

  constructor(url: string = 'http://localhost:8000') {
    this.url = url;
  }

  /**
   * 连接WebSocket
   */
  connect(): void {
    if (this.socket?.connected) {
      console.log('WebSocket already connected');
      return;
    }

    console.log(`Connecting to WebSocket: ${this.url}`);

    this.socket = io(this.url, {
      path: '/ws/socket.io',
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionAttempts: this.maxReconnectAttempts,
      reconnectionDelay: this.reconnectDelay,
    });

    // 连接成功
    this.socket.on('connect', () => {
      console.log('WebSocket connected');
      this.connected = true;
      this.reconnectAttempts = 0;

      // 触发连接事件
      this.emit('connected', { socketId: this.socket?.id });
    });

    // 断开连接
    this.socket.on('disconnect', (reason) => {
      console.log('WebSocket disconnected:', reason);
      this.connected = false;

      // 触发断开事件
      this.emit('disconnected', { reason });
    });

    // 连接错误
    this.socket.on('connect_error', (error) => {
      console.error('WebSocket connection error:', error);
      this.reconnectAttempts++;

      if (this.reconnectAttempts >= this.maxReconnectAttempts) {
        console.error('Max reconnection attempts reached');
        this.emit('error', { message: 'Connection failed' });
      }
    });

    // Agent状态更新
    this.socket.on('agent_state_changed', (data) => {
      console.log('Agent state changed:', data);
      this.emit('agent_update', data);
    });

    // 任务状态更新
    this.socket.on('task_state_changed', (data) => {
      console.log('Task state changed:', data);
      this.emit('task_update', data);
    });

    // 指标更新
    this.socket.on('metrics_updated', (data) => {
      console.log('Metrics updated');
      this.emit('metrics_update', data);
    });

    // 日志
    this.socket.on('log', (data) => {
      console.log('Log:', data);
      this.emit('log', data);
    });

    // 系统事件
    this.socket.on('system_event', (data) => {
      console.log('System event:', data);
      this.emit('system_event', data);
    });

    // Pong响应
    this.socket.on('pong', () => {
      this.emit('pong');
    });
  }

  /**
   * 断开连接
   */
  disconnect(): void {
    if (this.socket) {
      console.log('Disconnecting WebSocket');
      this.socket.disconnect();
      this.socket = null;
      this.connected = false;
    }
  }

  /**
   * 订阅频道
   */
  subscribe(channel: string): void {
    if (!this.socket?.connected) {
      console.warn('Cannot subscribe: WebSocket not connected');
      return;
    }

    console.log(`Subscribing to channel: ${channel}`);
    this.socket.emit('subscribe', { channel });
  }

  /**
   * 取消订阅频道
   */
  unsubscribe(channel: string): void {
    if (!this.socket?.connected) {
      console.warn('Cannot unsubscribe: WebSocket not connected');
      return;
    }

    console.log(`Unsubscribing from channel: ${channel}`);
    this.socket.emit('unsubscribe', { channel });
  }

  /**
   * 发送消息
   */
  send(event: string, data?: any): void {
    if (!this.socket?.connected) {
      console.warn('Cannot send: WebSocket not connected');
      return;
    }

    this.socket.emit(event, data);
  }

  /**
   * Ping服务器
   */
  ping(): void {
    this.send('ping');
  }

  /**
   * 添加事件监听器
   */
  on(event: string, handler: EventHandler): () => void {
    if (!this.eventHandlers.has(event)) {
      this.eventHandlers.set(event, new Set());
    }

    this.eventHandlers.get(event)!.add(handler);

    // 返回取消订阅函数
    return () => {
      this.off(event, handler);
    };
  }

  /**
   * 移除事件监听器
   */
  off(event: string, handler: EventHandler): void {
    const handlers = this.eventHandlers.get(event);
    if (handlers) {
      handlers.delete(handler);
    }
  }

  /**
   * 触发事件
   */
  private emit(event: string, data?: any): void {
    const handlers = this.eventHandlers.get(event);
    if (handlers) {
      handlers.forEach((handler) => {
        try {
          handler(data);
        } catch (error) {
          console.error(`Error in event handler for ${event}:`, error);
        }
      });
    }
  }

  /**
   * 获取连接状态
   */
  isConnected(): boolean {
    return this.connected && this.socket?.connected || false;
  }

  /**
   * 获取Socket ID
   */
  getId(): string | undefined {
    return this.socket?.id;
  }
}

// 创建全局WebSocket客户端实例
const wsClient = new WebSocketClient(
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
);

export default wsClient;
export { WebSocketClient };
