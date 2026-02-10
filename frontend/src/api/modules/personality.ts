/**
 * 人格配置API
 */
import { api } from '../client';

// 类型定义
export interface CorePersonality {
  name: string;
  role: string;
  backstory: string;
  language_style: string;
  use_emoji: boolean;
  catchphrases: string[];
  tone: string;
  communication_distance: string;
  value_alignment: string;
  traits: string[];
  virtues: string[];
  flaws: string[];
  taboos: string[];
  boundaries: string[];
}

export interface CognitionProfile {
  primary_style: string;
  secondary_style: string;
  risk_preference: string;
  reasoning_depth: string;
  creativity_level: number;
  learning_rate: number;
  expertise: Record<string, number>;
}

export interface PersonalityConfig {
  core: CorePersonality;
  cognition: CognitionProfile;
}

export interface AIGenerateRequest {
  description: string;
  current_config?: PersonalityConfig;
}

export interface PersonalityResponse {
  success: boolean;
  message: string;
  data?: PersonalityConfig;
}

// API方法
export const personalityApi = {
  // 获取人格配置
  get: (name: string) => api.get<PersonalityResponse>(`/personality/${name}`),

  // 更新人格配置
  update: (name: string, config: PersonalityConfig) =>
    api.put<PersonalityResponse>(`/personality/${name}`, config),

  // AI生成人格配置
  generate: (request: AIGenerateRequest) =>
    api.post<PersonalityResponse>('/personality/generate', request),

  // 列出所有人格
  list: () => api.get<PersonalityResponse>('/personality'),

  // 删除人格配置
  delete: (name: string) => api.delete<PersonalityResponse>(`/personality/${name}`),
};

export default personalityApi;
