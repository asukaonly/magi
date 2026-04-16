/**
 * Personality config API.
 */
import { api } from '../client';
import type { LLMConfig } from './config';

export interface BasicProfile {
  name: string;
  age: string;
  gender: string;
  description: string;
  avatar: string;
  occupation: string;
}

export interface CoreIdentity {
  inner_narrative: string;
  language_fingerprint: string;
  attention_bias: string;
}

export interface PersonaEntity {
  basic_profile: BasicProfile;
  core_identity: CoreIdentity;
}

export interface CachedPhrases {
  on_init: string[];
  on_error_generic: string[];
  on_success: string[];
  on_switch_attempt: string[];
}

export interface StateTransitionProtocolItem {
  trigger_type: string;
  trigger_condition: string;
  target_state_name: string;
  behavior_shift: string;
}

export interface PersonalityConfig {
  persona_entity: PersonaEntity;
  cached_phrases: CachedPhrases;
  appearance_prompt: string;
  state_transition_protocol: StateTransitionProtocolItem[];
}

export interface AIGenerateRequest {
  description: string;
  target_language?: string;
  current_config?: PersonalityConfig;
  llm_override?: LLMConfig;
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

// Defaults
export const DEFAULT_BASIC_PROFILE: BasicProfile = {
  name: 'AI Assistant',
  age: 'Unknown',
  gender: 'Unknown',
  description: '',
  avatar: '',
  occupation: 'Assistant',
};

export const DEFAULT_CORE_IDENTITY: CoreIdentity = {
  inner_narrative: '',
  language_fingerprint: '',
  attention_bias: '',
};

export const DEFAULT_PERSONA_ENTITY: PersonaEntity = {
  basic_profile: DEFAULT_BASIC_PROFILE,
  core_identity: DEFAULT_CORE_IDENTITY,
};

export const DEFAULT_CACHED_PHRASES: CachedPhrases = {
  on_init: ['Hi, I am online.', 'Ready when you are.'],
  on_error_generic: ['That failed. Let me retry.', 'Oops, tool hiccup.'],
  on_success: ['Done.', 'Handled.'],
  on_switch_attempt: ['Stay with me, I know your style.', 'Give me one more chance.'],
};

export const DEFAULT_STATE_TRANSITION_PROTOCOL: StateTransitionProtocolItem[] = [
  {
    trigger_type: '',
    trigger_condition: '',
    target_state_name: '',
    behavior_shift: '',
  },
];

export const DEFAULT_APPEARANCE_PROMPT = '';

export const DEFAULT_PERSONALITY_CONFIG: PersonalityConfig = {
  persona_entity: DEFAULT_PERSONA_ENTITY,
  cached_phrases: DEFAULT_CACHED_PHRASES,
  appearance_prompt: DEFAULT_APPEARANCE_PROMPT,
  state_transition_protocol: DEFAULT_STATE_TRANSITION_PROTOCOL,
};

// API methods
export const personalityApi = {
  get: (name: string) => api.get<PersonalityResponse>(`/personality/${name}`),
  update: (name: string, config: PersonalityConfig) =>
    api.put<PersonalityResponse>(`/personality/${name}`, config),
  updateWithAIName: (config: PersonalityConfig) =>
    api.put<PersonalityResponse>(`/personality/new?use_ai_name=true`, config),
  generate: (request: AIGenerateRequest) =>
    api.post<PersonalityResponse>('/personality/generate', request, {
      timeout: 120000,
    }),
  list: () => api.get<PersonalityResponse>('/personality'),
  delete: (name: string) => api.delete<PersonalityResponse>(`/personality/${name}`),
  getCurrent: () => api.get<PersonalityResponse>('/personality/current'),
  setCurrent: (name: string) => api.put<PersonalityResponse>('/personality/current', { name }),
  getGreeting: () => api.get<PersonalityResponse>('/personality/greeting'),
  bootstrapInit: (sessionId: string, userId: string = 'default_user') =>
    api.post<PersonalityResponse>('/personality/bootstrap/init', {
      session_id: sessionId,
      user_id: userId,
    }),
  bootstrapMessage: (request: {
    user_message: string;
    history: Array<{ role: string; content: string }>;
    user_id?: string;
    session_id: string;
  }) => api.post<PersonalityResponse>('/personality/bootstrap/message', request),
  compare: (fromName: string, toName: string) =>
    api.get<PersonalityCompareResponse>(`/personality/compare/${fromName}/${toName}`),
};

export default personalityApi;
