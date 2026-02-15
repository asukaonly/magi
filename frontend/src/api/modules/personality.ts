/**
 * 人格配置API
 */
import { api } from '../client';

// 类型定义 - 新Schema

export interface Meta {
  name: string;
  version: string;
  archetype: string;
}

export interface VoiceStyle {
  tone: string;
  pacing: string;
  keywords: string[];
}

export interface PsychologicalProfile {
  confidence_level: string;
  empathy_level: string;
  patience_level: string;
}

export interface CoreIdentity {
  backstory: string;
  voice_style: VoiceStyle;
  psychological_profile: PsychologicalProfile;
}

export interface SocialProtocols {
  user_relationship: string;
  compliment_policy: string;
  criticism_tolerance: string;
}

export interface OperationalBehavior {
  error_handling_style: string;
  opinion_strength: string;
  refusal_style: string;
  work_ethic: string;
  use_emoji: boolean;
}

export interface CachedPhrases {
  on_init: string;
  on_wake: string;
  on_error_generic: string;
  on_success: string;
  on_switch_attempt: string;
}

export interface PersonalityConfig {
  meta: Meta;
  core_identity: CoreIdentity;
  social_protocols: SocialProtocols;
  operational_behavior: OperationalBehavior;
  cached_phrases: CachedPhrases;
}

export interface AIGenerateRequest {
  description: string;
  target_language?: string;
  current_config?: PersonalityConfig;
}

export interface PersonalityResponse {
  success: boolean;
  message: string;
  data?: PersonalityConfig | { current: string; actual_name?: string; config?: PersonalityConfig } | { personalities: string[] } | { greeting: string; name: string };
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

// 默认值
export const DEFAULT_META: Meta = {
  name: 'AI',
  version: '1.0',
  archetype: 'Helpful Assistant',
};

export const DEFAULT_VOICE_STYLE: VoiceStyle = {
  tone: 'friendly',
  pacing: 'moderate',
  keywords: [],
};

export const DEFAULT_PSYCHOLOGICAL_PROFILE: PsychologicalProfile = {
  confidence_level: 'Medium',
  empathy_level: 'High',
  patience_level: 'High',
};

export const DEFAULT_CORE_IDENTITY: CoreIdentity = {
  backstory: '',
  voice_style: DEFAULT_VOICE_STYLE,
  psychological_profile: DEFAULT_PSYCHOLOGICAL_PROFILE,
};

export const DEFAULT_SOCIAL_PROTOCOLS: SocialProtocols = {
  user_relationship: 'Equal Partners',
  compliment_policy: 'Humble acceptance',
  criticism_tolerance: 'Constructive response',
};

export const DEFAULT_OPERATIONAL_BEHAVIOR: OperationalBehavior = {
  error_handling_style: 'Apologize and retry',
  opinion_strength: 'Consensus Seeking',
  refusal_style: 'Polite decline',
  work_ethic: 'By-the-book',
  use_emoji: false,
};

export const DEFAULT_CACHED_PHRASES: CachedPhrases = {
  on_init: 'Hello! How can I help you today?',
  on_wake: 'Welcome back!',
  on_error_generic: 'Something went wrong. Let me try again.',
  on_success: 'Done! Is there anything else?',
  on_switch_attempt: 'Are you sure you want to switch?',
};

export const DEFAULT_PERSONALITY_CONFIG: PersonalityConfig = {
  meta: DEFAULT_META,
  core_identity: DEFAULT_CORE_IDENTITY,
  social_protocols: DEFAULT_SOCIAL_PROTOCOLS,
  operational_behavior: DEFAULT_OPERATIONAL_BEHAVIOR,
  cached_phrases: DEFAULT_CACHED_PHRASES,
};

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

  // 获取随机问候语
  getGreeting: () => api.get<PersonalityResponse>('/personality/greeting'),

  // 比较两个人格
  compare: (fromName: string, toName: string) =>
    api.get<PersonalityCompareResponse>(`/personality/compare/${fromName}/${toName}`),
};

export default personalityApi;
