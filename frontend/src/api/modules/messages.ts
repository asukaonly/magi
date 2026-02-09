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

export interface MessageResponse {
  success: boolean;
  message: string;
  data?: {
    user_id: string;
    message_length: number;
    timestamp: number;
  };
}

export interface SensorStatus {
  sensor_type: string;
  enabled: boolean;
  perception_type: string;
  trigger_mode: string;
  queue_size: number;
}

export const messagesApi = {
  /**
   * 发送用户消息
   */
  sendMessage: async (request: UserMessageRequest): Promise<MessageResponse> => {
    const response = await api.post<MessageResponse>('/messages/send', request);
    return response.data;
  },

  /**
   * 获取传感器状态
   */
  getSensorStatus: async (): Promise<SensorStatus> => {
    const response = await api.get<SensorStatus>('/messages/sensor/status');
    return response.data;
  },

  /**
   * 启用传感器
   */
  enableSensor: async (): Promise<{ success: boolean; message: string }> => {
    const response = await api.post('/messages/sensor/enable');
    return response.data;
  },

  /**
   * 禁用传感器
   */
  disableSensor: async (): Promise<{ success: boolean; message: string }> => {
    const response = await api.post('/messages/sensor/disable');
    return response.data;
  },
};
