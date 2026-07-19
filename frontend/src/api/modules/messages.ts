/**
 * Messages API.
 */
import { api, unwrapGatewayPayload } from '../client';
import { DEFAULT_USER_ID } from '@/constants';
import type { RecallFeedbackRequest } from '@/domain/chat/recall-feedback';

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
  reply_to_message_id?: string | null;
  workspace_path?: string | null;
  client_turn_id?: string;
  recall_feedback?: RecallFeedbackRequest;
  interaction_kind?: 'first_context_story';
  first_context?: {
    question_id: string;
    question_text: string;
  };
  metadata?: Record<string, any>;
}

export interface ChatReplyPreview {
  message_id: string;
  role: 'user' | 'assistant';
  message_kind?: string | null;
  content_excerpt: string;
}

export interface ChatMessageLabel {
  kind: string;
  text: string;
  applied_by: string;
  source: string;
  created_at_ms: number;
}

export interface ChatRunState {
  state: string;
  run_id?: string | null;
  run_revision?: number;
  run_disposition?: string | null;
  can_cancel?: boolean;
  can_detach?: boolean;
  error_text?: string | null;
  completed_at_ms?: number | null;
}

// Backend response data shape
export interface MessageData {
  message_id?: string | null;
  user_id: string;
  session_id?: string;
  turn_id?: string | null;
  handled_as?: string | null;
  ask_request_id?: string | null;
  message_length: number;
  attachment_count?: number;
  timestamp: number;
}

export interface ChatHistoryMessage {
  message_id?: string | null;
  message_kind?: string | null;
  persona_id?: string | null;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  turn_id?: string | null;
  kind?: 'user' | 'assistant' | 'status' | null;
  trace_display_mode?: string | null;
  allow_trace_collapse?: boolean;
  trace_summary?: Record<string, any> | null;
  trace_available?: boolean;
  run_state?: ChatRunState | null;
  attachments?: ChatAttachment[];
  reply_to?: ChatReplyPreview | null;
  label?: ChatMessageLabel | null;
  payload?: Record<string, unknown> | null;
}

export interface ConversationHistory {
  user_id: string;
  session_id?: string;
  messages: ChatHistoryMessage[];
  count: number;
  history_version?: number;
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
  history_version?: number;
}

export interface SessionListResponse {
  user_id: string;
  sessions: ChatSessionListItem[];
  count: number;
}

export interface CancelRunData {
  user_id: string;
  session_id: string;
  run_id?: string;
  revision?: number;
  status?: string;
  cancel_reason?: string | null;
  cancel_requested_by?: string | null;
  cancel_anchor_turn_id?: string | null;
  cancelled_orchestration_ids?: string[];
}

export interface DetachRunData {
  user_id: string;
  session_id: string;
  run_id?: string;
  revision?: number;
  status?: string;
  detach_reason?: string | null;
  detach_requested_by?: string | null;
  detach_anchor_turn_id?: string | null;
}

export interface ExecutionPlanStepSummary {
  subtask_id?: string | null;
  label: string;
  status: string;
}

export interface ExecutionPlanSummary {
  planner?: string | null;
  parallel_mode: string;
  total_steps: number;
  remaining_steps: number;
  steps: ExecutionPlanStepSummary[];
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
  plan_summary?: ExecutionPlanSummary | null;
  continued_from_turn_id?: string | null;
  continued_from_trace_id?: string | null;
  superseded_by_turn_id?: string | null;
  supersession_reason?: string | null;
  total_input_tokens?: number;
  total_output_tokens?: number;
  total_reasoning_tokens?: number;
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

type ClearHistoryResponse = {
  success: boolean;
  message: string;
  user_id: string;
  session_id: string;
  cleared_message_ids: string[];
  cleared_turn_ids: string[];
  cleanup_pending: boolean;
};
type CreateSessionResponse = {
  success: boolean;
  user_id: string;
  session_id: string | null;
  workspace_path?: string | null;
};
type RenameSessionResponse = { success: boolean; user_id: string; session: { session_id: string; title: string } };
type UpdateSessionWorkspaceResponse = { success: boolean; user_id: string; session: ChatSessionListItem };
type RecentWorkspacesResponse = { paths: string[] };
type DeleteMessageResponse = {
  success: boolean;
  user_id: string;
  session_id: string;
  deleted_message_id: string;
  cleanup_pending: boolean;
};
type DeleteSessionResponse = {
  success: boolean;
  user_id: string;
  deleted_session_id: string;
  cleanup_pending: boolean;
};
type TraceResponse = {
  success: boolean;
  user_id: string;
  session_id: string;
  turn_id: string;
  trace: ExecutionTraceSnapshot | null;
};

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
    return unwrapGatewayPayload(response);
  },

  /** Clear conversation history */
  clearHistory: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string
  ): Promise<ClearHistoryResponse> => {
    const response = await api.post<ClearHistoryResponse>('/messages/history/clear', null, {
      params: { user_id: userId, session_id: sessionId },
    });
    return unwrapGatewayPayload<ClearHistoryResponse>(response);
  },

  createNewSession: async (
    userId: string = DEFAULT_USER_ID,
    clientSessionId?: string,
  ): Promise<CreateSessionResponse> => {
    const response = await api.post<CreateSessionResponse>('/messages/session/new', null, {
      params: {
        user_id: userId,
        client_session_id: clientSessionId,
      },
    });
    return unwrapGatewayPayload(response);
  },

  renameSession: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string,
    title: string
  ): Promise<RenameSessionResponse> => {
    const response = await api.patch<RenameSessionResponse>(
      `/messages/session/${encodeURIComponent(sessionId)}`,
      {
        user_id: userId,
        title,
      }
    );
    return unwrapGatewayPayload(response);
  },

  updateSessionWorkspace: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string,
    workspacePath: string | null,
  ): Promise<UpdateSessionWorkspaceResponse> => {
    const response = await api.patch<UpdateSessionWorkspaceResponse>(
      `/messages/session/${encodeURIComponent(sessionId)}/workspace`,
      {
        user_id: userId,
        workspace_path: workspacePath,
      }
    );
    return unwrapGatewayPayload(response);
  },

  getRecentWorkspaces: async (): Promise<RecentWorkspacesResponse> => {
    const response = await api.get<RecentWorkspacesResponse>('/messages/workspaces/recent');
    return unwrapGatewayPayload(response);
  },

  rememberWorkspace: async (path: string): Promise<RecentWorkspacesResponse> => {
    const response = await api.post<RecentWorkspacesResponse>('/messages/workspaces/recent', { path });
    return unwrapGatewayPayload(response);
  },

  cancelRun: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string,
    options: {
      reason?: string;
      turnId?: string;
      requestedBy?: string;
    } = {},
  ): Promise<{ success: boolean; message: string; data?: CancelRunData }> => {
    const response = await api.post<CancelRunData>(
      `/messages/session/${encodeURIComponent(sessionId)}/cancel-run`,
      {
        user_id: userId,
        reason: options.reason || 'user_cancel',
        turn_id: options.turnId || null,
        requested_by: options.requestedBy || 'user',
      }
    );
    return response;
  },

  detachRun: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string,
    options: {
      reason?: string;
      turnId?: string;
      requestedBy?: string;
    } = {},
  ): Promise<{ success: boolean; message: string; data?: DetachRunData }> => {
    const response = await api.post<DetachRunData>(
      `/messages/session/${encodeURIComponent(sessionId)}/detach-run`,
      {
        user_id: userId,
        reason: options.reason || 'user_detach',
        turn_id: options.turnId || null,
        requested_by: options.requestedBy || 'user',
      }
    );
    return response;
  },

  labelMessage: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string,
    messageId: string,
    label: Omit<ChatMessageLabel, 'created_at_ms'> & { created_at_ms?: number },
  ): Promise<{ success: boolean; message?: string; data?: { message_id: string; label: ChatMessageLabel } }> => {
    const response = await api.post<{ message_id: string; label: ChatMessageLabel }>(
      `/messages/session/${encodeURIComponent(sessionId)}/message/${encodeURIComponent(messageId)}/label`,
      {
        user_id: userId,
        ...label,
      }
    );
    return response;
  },

  deleteMessage: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string,
    messageId: string,
  ): Promise<DeleteMessageResponse> => {
    const response = await api.delete<DeleteMessageResponse>(
      `/messages/session/${encodeURIComponent(sessionId)}/message/${encodeURIComponent(messageId)}`,
      {
        params: { user_id: userId },
      }
    );
    return unwrapGatewayPayload(response);
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
    return unwrapGatewayPayload<{ attachment: ChatAttachment }>(response).attachment;
  },

  deleteSession: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string
  ): Promise<DeleteSessionResponse> => {
    const response = await api.delete<DeleteSessionResponse>(
      `/messages/session/${encodeURIComponent(sessionId)}`,
      {
        params: { user_id: userId },
      }
    );
    return unwrapGatewayPayload(response);
  },

  listSessions: async (
    userId: string = DEFAULT_USER_ID,
    limit: number = 30
  ): Promise<SessionListResponse> => {
    const response = await api.get<SessionListResponse>('/messages/sessions', {
      params: { user_id: userId, limit },
    });
    return unwrapGatewayPayload(response);
  },

  getTrace: async (
    userId: string = DEFAULT_USER_ID,
    sessionId: string,
    turnId: string
  ): Promise<TraceResponse> => {
    const response = await api.get<TraceResponse>('/messages/trace', {
      params: { user_id: userId, session_id: sessionId, turn_id: turnId },
    });
    return unwrapGatewayPayload(response);
  },
};
