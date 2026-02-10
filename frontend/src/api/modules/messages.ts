/**
 * 消息API
 */
import { api } from '../client';

export interface UserMessageRequest {
  message: string;
  user_id?: string;
  session_id?: string;
  metadata?: Record<string, any>;
}

// 后端实际返回的 data 结构
export interface MessageData {
  user_id: string;
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
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
}

export interface ConversationHistory {
  user_id: string;
  messages: ChatHistoryMessage[];
  count: number;
}

export const messagesApi = {
  /**
   * 发送用户消息
   */
  sendMessage: async (request: UserMessageRequest): Promise<{ success: boolean; message: string; data?: MessageData }> => {
    const response = await api.post<MessageData>('/messages/send', request);
    return response;
  },

  /**
   * 获取传感器状态
   */
  getSensorStatus: async (): Promise<SensorStatus> => {
    const response = await api.get<SensorStatus>('/messages/sensor/status');
    return response;
  },

  /**
   * 启用传感器
   */
  enableSensor: async (): Promise<{ success: boolean; message: string }> => {
    const response = await api.post<{ success: boolean; message: string }>('/messages/sensor/enable');
    return response;
  },

  /**
   * 禁用传感器
   */
  disableSensor: async (): Promise<{ success: boolean; message: string }> => {
    const response = await api.post<{ success: boolean; message: string }>('/messages/sensor/disable');
    return response;
  },

  /**
   * 获取对话历史
   */
  getHistory: async (userId: string = 'web_user'): Promise<ConversationHistory> => {
    const response = await api.get<ConversationHistory>('/messages/history', {
      params: { user_id: userId },
    });
    return response;
  },

  /**
   * 清空对话历史
   */
  clearHistory: async (userId: string = 'web_user'): Promise<{ success: boolean; message: string; user_id: string }> => {
    const response = await api.post<{ success: boolean; message: string; user_id: string }>('/messages/history/clear', null, {
      params: { user_id: userId },
    });
    return response;
  },
};
