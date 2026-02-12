/**
 * 配置管理API
 */
import { api } from '../client';

// 类型定义
export interface SystemConfig {
  agent: {
    name: string;
    description?: string;
  };
  llm: {
    provider: 'openai' | 'anthropic' | 'local';
    model: string;
    api_key?: string;
    base_url?: string;
  };
  loop: {
    strategy: 'step' | 'wave' | 'continuous';
    interval: number;
  };
  message_bus: {
    backend: 'memory' | 'sqlite' | 'redis';
    max_size?: number;
  };
  memory: {
    backend: 'memory' | 'sqlite' | 'chromadb';
    path?: string;
  };
  websocket: {
    enabled: boolean;
    port?: number;
  };
  log: {
    level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
    path?: string;
  };
}

// API方法
export const configApi = {
  // 获取配置
  get: () => api.get<SystemConfig>('/config'),

  // 更新配置
  update: (config: Partial<SystemConfig>) =>
    api.put<SystemConfig>('/config', config),

  // 重置配置为默认值
  reset: () => api.post<SystemConfig>('/config/reset', {}),

  // 获取配置模板
  getTemplate: () => api.get<SystemConfig>('/config/template'),
};

export default configApi;
