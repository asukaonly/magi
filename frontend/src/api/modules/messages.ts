/**
 * Messages API.
 */
import { api } from '../client';

export interface UserMessageRequest {
  message: string;
  user_id?: string;
  session_id?: string;
  metadata?: Record<string, any>;
}

// Backend response data shape
export interface MessageData {
  user_id: string;
  session_id?: string;
  message_length: number;
  timestamp: number;
}

export interface SensorStatus {
  sensor_type: string;
  enabled: boolean;
  perception_type: string;
  trigger_mode: string;
  queue_size: number;
}

export interface ChatHistoryMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  turn_id?: string | null;
  kind?: 'user' | 'assistant' | 'status' | null;
  trace_summary?: Record<string, any> | null;
  trace_available?: boolean;
}

export interface ConversationHistory {
  user_id: string;
  session_id?: string;
  messages: ChatHistoryMessage[];
  count: number;
}

export interface SessionInfo {
  user_id: string;
  session_id: string | null;
}

export interface ChatSessionListItem {
  session_id: string;
  title: string;
  last_message_preview: string;
  last_user_message_preview?: string;
  title_overridden?: boolean;
  last_timestamp: number;
  message_count: number;
}

export interface SessionListResponse {
  user_id: string;
  current_session_id: string | null;
  sessions: ChatSessionListItem[];
  count: number;
}

export interface ExecutionTraceSummary {
  turn_id: string;
  mode: string;
  status: string;
  headline: string;
  active_steps: number;
  completed_steps: number;
  failed_steps: number;
  duration_seconds: number;
  trace_available: boolean;
  orchestration_id?: string | null;
}

export interface ExecutionTraceNode {
  id: string;
  kind: string;
  label: string;
  status: string;
  started_at?: number | null;
  ended_at?: number | null;
  result_preview?: string;
  error?: string | null;
  metadata?: Record<string, any>;
  children: ExecutionTraceNode[];
}

export interface ExecutionTraceSnapshot {
  turn_id: string;
  user_id: string;
  session_id: string;
  status: string;
  mode: string;
  orchestration_id?: string | null;
  started_at?: number | null;
  ended_at?: number | null;
  summary: ExecutionTraceSummary;
  root: ExecutionTraceNode;
}

export const messagesApi = {
  /** Send user message */
  sendMessage: async (request: UserMessageRequest): Promise<{ success: boolean; message: string; data?: MessageData }> => {
    const response = await api.post<MessageData>('/messages/send', request);
    return response;
  },

  /** Get sensor status */
  getSensorStatus: async (): Promise<SensorStatus> => {
    const response = await api.get<SensorStatus>('/messages/sensor/status');
    return (response.data || response) as SensorStatus;
  },

  /** Enable sensor */
  enableSensor: async (): Promise<{ success: boolean; message: string }> => {
    const response = await api.post<{ success: boolean; message: string }>('/messages/sensor/enable');
    return response;
  },

  /** Disable sensor */
  disableSensor: async (): Promise<{ success: boolean; message: string }> => {
    const response = await api.post<{ success: boolean; message: string }>('/messages/sensor/disable');
    return response;
  },

  /** Get conversation history */
  getHistory: async (userId: string = 'web_user', sessionId?: string): Promise<ConversationHistory> => {
    const response = await api.get<ConversationHistory>('/messages/history', {
      params: { user_id: userId, session_id: sessionId },
    });
    return (response.data || response) as ConversationHistory;
  },

  /** Clear conversation history */
  clearHistory: async (
    userId: string = 'web_user',
    sessionId?: string
  ): Promise<{ success: boolean; message: string; user_id: string; session_id?: string }> => {
    const response = await api.post<{ success: boolean; message: string; user_id: string }>('/messages/history/clear', null, {
      params: { user_id: userId, session_id: sessionId },
    });
    return (response.data || response) as { success: boolean; message: string; user_id: string; session_id?: string };
  },

  getCurrentSession: async (userId: string = 'web_user'): Promise<SessionInfo> => {
    const response = await api.get<SessionInfo>('/messages/session/current', {
      params: { user_id: userId },
    });
    return (response.data || response) as SessionInfo;
  },

  createNewSession: async (userId: string = 'web_user'): Promise<{ success: boolean; user_id: string; session_id: string | null }> => {
    const response = await api.post<{ success: boolean; user_id: string; session_id: string | null }>('/messages/session/new', null, {
      params: { user_id: userId },
    });
    return (response.data || response) as { success: boolean; user_id: string; session_id: string | null };
  },

  renameSession: async (
    userId: string = 'web_user',
    sessionId: string,
    title: string
  ): Promise<{ success: boolean; user_id: string; session: { session_id: string; title: string } }> => {
    const response = await api.patch<{ success: boolean; user_id: string; session: { session_id: string; title: string } }>(
      `/messages/session/${encodeURIComponent(sessionId)}`,
      {
        user_id: userId,
        title,
      }
    );
    return (response.data || response) as { success: boolean; user_id: string; session: { session_id: string; title: string } };
  },

  deleteSession: async (
    userId: string = 'web_user',
    sessionId: string
  ): Promise<{ success: boolean; user_id: string; deleted_session_id: string; current_session_id: string | null }> => {
    const response = await api.delete<{ success: boolean; user_id: string; deleted_session_id: string; current_session_id: string | null }>(
      `/messages/session/${encodeURIComponent(sessionId)}`,
      {
        params: { user_id: userId },
      }
    );
    return (response.data || response) as { success: boolean; user_id: string; deleted_session_id: string; current_session_id: string | null };
  },

  listSessions: async (
    userId: string = 'web_user',
    limit: number = 30
  ): Promise<SessionListResponse> => {
    const response = await api.get<SessionListResponse>('/messages/sessions', {
      params: { user_id: userId, limit },
    });
    return (response.data || response) as SessionListResponse;
  },

  getTrace: async (
    userId: string = 'web_user',
    sessionId: string,
    turnId: string
  ): Promise<{ success: boolean; user_id: string; session_id: string; turn_id: string; trace: ExecutionTraceSnapshot | null }> => {
    const response = await api.get<{ success: boolean; user_id: string; session_id: string; turn_id: string; trace: ExecutionTraceSnapshot | null }>('/messages/trace', {
      params: { user_id: userId, session_id: sessionId, turn_id: turnId },
    });
    return (response.data || response) as { success: boolean; user_id: string; session_id: string; turn_id: string; trace: ExecutionTraceSnapshot | null };
  },
};
