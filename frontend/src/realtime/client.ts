export interface RealtimeMessage {
  type?: string;
  data?: any;
  event?: string;
  channel?: string;
  sid?: string;
  message?: string;
  [key: string]: unknown;
}

type RealtimeListener = (message: RealtimeMessage) => void;

type RealtimeStatus = {
  connected: boolean;
  reconnectAttempts: number;
  lastError: string | null;
};

type RealtimeStatusListener = (status: RealtimeStatus) => void;

const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_RECONNECT_DELAY = 1000;
const MAX_RECONNECT_DELAY = 30000;
const READY_STATE_CONNECTING = 0;
const READY_STATE_OPEN = 1;

export class RealtimeClient {
  private socket: WebSocket | null = null;
  private url: string | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private listeners = new Set<RealtimeListener>();
  private statusListeners = new Set<RealtimeStatusListener>();
  private closedByClient = false;
  private lastError: string | null = null;

  connect(url: string): void {
    this.url = url;
    this.closedByClient = false;
    if (this.socket?.readyState === READY_STATE_OPEN || this.socket?.readyState === READY_STATE_CONNECTING) {
      return;
    }
    this.openSocket();
  }

  disconnect(reason = 'shell-unmount'): void {
    this.closedByClient = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      this.socket.close(1000, reason);
      this.socket = null;
    }
    this.reconnectAttempts = 0;
    this.lastError = null;
    this.emitStatus();
  }

  send(message: Record<string, unknown>): void {
    if (this.socket?.readyState !== READY_STATE_OPEN) {
      return;
    }
    this.socket.send(JSON.stringify(message));
  }

  subscribe(listener: RealtimeListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  subscribeStatus(listener: RealtimeStatusListener): () => void {
    this.statusListeners.add(listener);
    listener(this.getStatus());
    return () => {
      this.statusListeners.delete(listener);
    };
  }

  private openSocket(): void {
    if (!this.url) {
      return;
    }

    const socket = new WebSocket(this.url);
    this.socket = socket;

    socket.onopen = () => {
      this.reconnectAttempts = 0;
      this.lastError = null;
      this.emitStatus();
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as RealtimeMessage;
        this.listeners.forEach((listener) => listener(payload));
      } catch {
        // Ignore malformed payloads.
      }
    };

    socket.onerror = () => {
      this.lastError = 'Connection error';
      this.emitStatus();
    };

    socket.onclose = (event) => {
      this.socket = null;
      if (this.closedByClient) {
        this.emitStatus();
        return;
      }
      this.scheduleReconnect(event.code !== 1000);
    };
  }

  private scheduleReconnect(shouldReconnect: boolean): void {
    if (!shouldReconnect) {
      this.emitStatus();
      return;
    }
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      this.lastError = 'Reconnect failed';
      this.emitStatus();
      return;
    }
    const delay = Math.min(
      BASE_RECONNECT_DELAY * Math.pow(2, this.reconnectAttempts),
      MAX_RECONNECT_DELAY
    ) + Math.random() * 1000;
    this.reconnectAttempts += 1;
    this.emitStatus();
    this.reconnectTimer = setTimeout(() => {
      this.openSocket();
    }, delay);
  }

  private getStatus(): RealtimeStatus {
    return {
      connected: this.socket?.readyState === READY_STATE_OPEN,
      reconnectAttempts: this.reconnectAttempts,
      lastError: this.lastError,
    };
  }

  private emitStatus(): void {
    const status = this.getStatus();
    this.statusListeners.forEach((listener) => listener(status));
  }
}
