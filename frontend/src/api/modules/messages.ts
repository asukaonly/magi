/**
 * Messages API.
 */
import { api } from '../client';
import { DEFAULT_USER_ID } from '@/constants';

export interface ChatAttachment {
  attachment_id: string;
  kind: string;
  original_name: string;
  mime_type?: string;
  size_bytes?: number;
  storage_path?: string;
  sha256?: string;
  parse_status?: string;
  derived_text_excerpt?: string;
  derived_text_path?: string;
  [key: string]: any;
}

export interface UserMessageRequest {
  message: string;
  user_id?: string;
  session_id: string;
  attachments?: ChatAttachment[];
  workspace_path?: string | null;
  client_turn_id?: string;
  metadata?: Record<string, any>;
}

// Backend response data shape
export interface MessageData {
  user_id: string;
  session_id?: string;
  message_length: number;
  timestamp: number;
}

export interface ChatHistoryMessage {
  message_id?: string | null;
  message_kind?: string | null;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  turn_id?: string | null;
  kind?: 'user' | 'assistant' | 'status' | null;
  trace_display_mode?: string | null;
  allow_trace_collapse?: boolean;
  trace_summary?: Record<string, any> | null;
  trace_available?: boolean;
  attachments?: ChatAttachment[];
}

export interface ConversationHistory {
  user_id: string;
  session_id?: string;
  messages: ChatHistoryMessage[];
  count: number;
}

export interface ChatSessionListItem {
  session_id: string;
  title: string;
  last_message_preview: string;
  last_user_message_preview?: string;
  title_overridden?: boolean;
  last_timestamp: number;
  message_count: number;
  workspace_path?: string | null;
}

export interface SessionListResponse {
  user_id: string;
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
  continued_from_turn_id?: string | null;
  continued_from_trace_id?: string | null;
  superseded_by_turn_id?: string | null;
  supersession_reason?: string | null;
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
  continued_from_turn_id?: string | null;
  continued_from_trace_id?: string | null;
  superseded_by_turn_id?: string | null;
  supersession_reason?: string | null;
  summary: ExecutionTraceSummary;
  root: ExecutionTraceNode;
}

export const messagesApi = {
  /** Send user message */
  sendMessage: async (request: UserMessageRequest): Promise<{ success: boolean; message: string; data?: MessageData }> => {
    const response = await api.post<MessageData>('/messages/send', request);
    return response;
  },

  /** Get conversation history */
  getHistory: async (userId: string = DEFAULT_USER_ID, sessionId: string): Promise<ConversationHistory> => {
    const response = await api.get<ConversationHistory>('/messages/history', {
      params: { user_id: userId, session_id: sessionId },
    });
    return (response.data || response) as ConversationHistory;
  },

  /** Clear conversation history */
  clearHistory: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string
  ): Promise<{ success: boolean; message: string; user_id: string; session_id?: string }> => {
    const response = await api.post<{ success: boolean; message: string; user_id: string }>('/messages/history/clear', null, {
      params: { user_id: userId, session_id: sessionId },
    });
    return (response.data || response) as { success: boolean; message: string; user_id: string; session_id?: string };
  },

  createNewSession: async (userId: string = DEFAULT_USER_ID): Promise<{ success: boolean; user_id: string; session_id: string | null; workspace_path?: string | null }> => {
    const response = await api.post<{ success: boolean; user_id: string; session_id: string | null; workspace_path?: string | null }>('/messages/session/new', null, {
      params: { user_id: userId },
    });
    return (response.data || response) as { success: boolean; user_id: string; session_id: string | null; workspace_path?: string | null };
  },

  renameSession: async (
    userId: string = DEFAULT_USER_ID,
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

  updateSessionWorkspace: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string,
    workspacePath: string | null,
  ): Promise<{ success: boolean; user_id: string; session: ChatSessionListItem }> => {
    const response = await api.patch<{ success: boolean; user_id: string; session: ChatSessionListItem }>(
      `/messages/session/${encodeURIComponent(sessionId)}/workspace`,
      {
        user_id: userId,
        workspace_path: workspacePath,
      }
    );
    return (response.data || response) as { success: boolean; user_id: string; session: ChatSessionListItem };
  },

  uploadAttachment: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string,
    turnId: string,
    file: File,
  ): Promise<ChatAttachment> => {
    const formData = new FormData();
    formData.append('user_id', userId);
    formData.append('turn_id', turnId);
    formData.append('file', file);
    const response = await api.post<{ attachment: ChatAttachment }>(
      `/messages/session/${encodeURIComponent(sessionId)}/attachments`,
      formData,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
      }
    );
    return ((response.data || response) as { attachment: ChatAttachment }).attachment;
  },

  deleteSession: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string
  ): Promise<{ success: boolean; user_id: string; deleted_session_id: string }> => {
    const response = await api.delete<{ success: boolean; user_id: string; deleted_session_id: string }>(
      `/messages/session/${encodeURIComponent(sessionId)}`,
      {
        params: { user_id: userId },
      }
    );
    return (response.data || response) as { success: boolean; user_id: string; deleted_session_id: string };
  },

  listSessions: async (
    userId: string = DEFAULT_USER_ID,
    limit: number = 30
  ): Promise<SessionListResponse> => {
    const response = await api.get<SessionListResponse>('/messages/sessions', {
      params: { user_id: userId, limit },
    });
    return (response.data || response) as SessionListResponse;
  },

  getTrace: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string,
    turnId: string
  ): Promise<{ success: boolean; user_id: string; session_id: string; turn_id: string; trace: ExecutionTraceSnapshot | null }> => {
    const response = await api.get<{ success: boolean; user_id: string; session_id: string; turn_id: string; trace: ExecutionTraceSnapshot | null }>('/messages/trace', {
      params: { user_id: userId, session_id: sessionId, turn_id: turnId },
    });
    return (response.data || response) as { success: boolean; user_id: string; session_id: string; turn_id: string; trace: ExecutionTraceSnapshot | null };
  },
};
