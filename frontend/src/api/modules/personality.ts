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
  data?: PersonalityConfig | { current: string; actual_name?: string; config?: PersonalityConfig } | { personalities: string[] };
}

export interface PersonalityDiff {
  field: string;
  field_label: string;
  old_value: any;
  new_value: any;
}

export interface PersonalityCompareResponse {
  success: boolean;
  message: string;
  from_personality: string;
  to_personality: string;
  diffs: PersonalityDiff[];
  from_config?: PersonalityConfig;
  to_config?: PersonalityConfig;
}

// API方法
export const personalityApi = {
  // 获取人格配置
  get: (name: string) => api.get<PersonalityResponse>(`/personality/${name}`),

  // 更新人格配置
  update: (name: string, config: PersonalityConfig) =>
    api.put<PersonalityResponse>(`/personality/${name}`, config),

  // 使用AI名字创建/更新人格配置
  updateWithAIName: (config: PersonalityConfig) =>
    api.put<PersonalityResponse>(`/personality/new?use_ai_name=true`, config),

  // AI生成人格配置
  generate: (request: AIGenerateRequest) =>
    api.post<PersonalityResponse>('/personality/generate', request),

  // 列出所有人格
  list: () => api.get<PersonalityResponse>('/personality'),

  // 删除人格配置
  delete: (name: string) => api.delete<PersonalityResponse>(`/personality/${name}`),

  // 获取当前激活的人格
  getCurrent: () => api.get<PersonalityResponse>('/personality/current'),

  // 设置当前激活的人格
  setCurrent: (name: string) => api.put<PersonalityResponse>('/personality/current', { name }),

  // 比较两个人格
  compare: (fromName: string, toName: string) =>
    api.get<PersonalityCompareResponse>(`/personality/compare/${fromName}/${toName}`),
};

export default personalityApi;
