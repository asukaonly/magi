/**
 * Persona registry API – wraps /api/personas/* endpoints.
 *
 * All persona CRUD, active-persona management, seed previews, and seeding
 * are routed through UUID-keyed persona registry.
 */
import { api } from '../client';
import type { LLMConfig } from './config';
import { getRuntimeConfig } from '@/runtime/config';

// ---------------------------------------------------------------------------
// Personality config types (schema of a persona's `config` field)
// ---------------------------------------------------------------------------

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

export interface StateTransitionProtocolItem {
  trigger_type: string;
  trigger_condition: string;
  target_state_name: string;
  behavior_shift: string;
}

export interface PersonaLayerItem {
  layer_id: string;
  unlock_condition: Record<string, unknown> | null;
  persona_override: Record<string, string> | null;
  behavior_hints: string[] | null;
}

export interface PersonalityConfig {
  persona_entity: PersonaEntity;
  appearance_prompt: string;
  state_transition_protocol: StateTransitionProtocolItem[];
  persona_layers: PersonaLayerItem[];
}

export interface AIGenerateRequest {
  description: string;
  target_language?: string;
  current_config?: PersonalityConfig;
  llm_override?: LLMConfig;
}

// ---------------------------------------------------------------------------
// Personality config defaults
// ---------------------------------------------------------------------------

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

export const DEFAULT_STATE_TRANSITION_PROTOCOL: StateTransitionProtocolItem[] = [
  {
    trigger_type: '',
    trigger_condition: '',
    target_state_name: '',
    behavior_shift: '',
  },
];

export const DEFAULT_PERSONALITY_CONFIG: PersonalityConfig = {
  persona_entity: DEFAULT_PERSONA_ENTITY,
  appearance_prompt: '',
  state_transition_protocol: DEFAULT_STATE_TRANSITION_PROTOCOL,
  persona_layers: [],
};

// ---------------------------------------------------------------------------
// Registry types
// ---------------------------------------------------------------------------

export interface PersonaSummary {
  persona_id: string;
  name: string;
  slug: string;
  locale: string;
  avatar_path: string;
  group_name: string;
  sort_order: number;
  is_builtin: boolean;
  description: string;
}

export interface PersonaDetail {
  persona_id: string;
  name: string;
  slug: string;
  locale: string;
  config: Record<string, any>;
  avatar_path: string;
  group_name: string;
  sort_order: number;
  is_builtin: boolean;
  seed_slug: string | null;
  created_at: number;
  updated_at: number;
}

export interface PersonaListResponse {
  success: boolean;
  data: PersonaSummary[];
}

export interface PersonaDetailResponse {
  success: boolean;
  data: PersonaDetail | null;
}

export interface ActivePersonaResponse {
  success: boolean;
  persona_id: string | null;
}

export interface SeedPreview {
  seed_slug: string;
  name: string;
  description: string;
  avatar: string;
  group: string;
  order: number;
}

export interface SeedPreviewResponse {
  success: boolean;
  data: SeedPreview[];
}

export interface SeedResponse {
  success: boolean;
  created_ids: string[];
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

export const personasApi = {
  /** List all registered personas. */
  list: () => api.get<PersonaSummary[]>('/personas/'),

  /** Get full detail for a persona by ID. */
  get: (personaId: string) => api.get<PersonaDetail>('/personas/' + personaId),

  /** Create a new custom persona. Returns detail including assigned persona_id. */
  create: (payload: { config_json: string; locale?: string; slug?: string }) =>
    api.post<PersonaDetail>('/personas/', payload),

  /** Update mutable fields of an existing persona. */
  update: (
    personaId: string,
    payload: {
      name?: string;
      config_json?: string;
      slug?: string;
      avatar_path?: string;
      sort_order?: number;
    },
  ) => api.put<PersonaDetail>('/personas/' + personaId, payload),

  /** Delete a persona (cannot delete the active one). */
  delete: (personaId: string) => api.delete('/personas/' + personaId),

  /** Get the active persona ID. Returns persona_id at the top level. */
  getActive: () =>
    api.get('/personas/active') as unknown as Promise<{ success: boolean; persona_id: string | null }>,

  /** Switch the active persona. Returns persona_id at the top level. */
  setActive: (personaId: string) =>
    api.put('/personas/active', { persona_id: personaId }) as unknown as Promise<{ success: boolean; persona_id: string | null }>,

  /** Get lightweight seed previews (for onboarding). */
  seedPreviews: (locale: string = 'en') =>
    api.get<SeedPreview[]>('/personas/seed-previews', { locale }),

  /** Seed builtin personas from bundled presets (idempotent). */
  seed: (locale: string = 'en') =>
    api.post<SeedResponse>('/personas/seed', null, { params: { locale } }),

  /** Fetch full preset config by seed slug and locale (for onboarding form). */
  getPresetConfig: (seedSlug: string, locale: string = 'en') =>
    api.get<PersonalityConfig>(`/personalities/${seedSlug}`, { lang: locale }),

  // -----------------------------------------------------------------------
  // Avatar helpers
  // -----------------------------------------------------------------------

  /** Resolve an avatar value to a full URL. */
  getAvatarUrl: (avatar?: string): string => {
    if (!avatar) return '';
    if (avatar.startsWith('http://') || avatar.startsWith('https://') || avatar.startsWith('data:')) {
      return avatar;
    }
    const origin = getRuntimeConfig().apiBaseUrl.replace(/\/api$/, '');
    if (avatar.startsWith('/')) return `${origin}${avatar}`;
    return `${origin}/static/avatars/${encodeURIComponent(avatar)}`;
  },

  /** Upload an avatar image. */
  uploadAvatar: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<{ filename: string; url: string }>('/personalities/avatar/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  // -----------------------------------------------------------------------
  // Personality generation & bootstrap (legacy endpoints, still active)
  // -----------------------------------------------------------------------

  /** AI-generate a personality config from a description. */
  generate: (request: AIGenerateRequest) =>
    api.post<{ success: boolean; data?: PersonalityConfig }>('/personality/generate', request, {
      timeout: 120000,
    }),

  /** Get a greeting from the active persona. */
  getGreeting: () =>
    api.get<{ greeting: string; name: string; needs_bootstrap?: boolean }>('/personality/greeting'),

  /** Init a bootstrap session for the active persona. */
  bootstrapInit: (sessionId: string, userId: string = 'default_user') =>
    api.post<{ bootstrap_active: boolean; opening: string | null }>('/personality/bootstrap/init', {
      session_id: sessionId,
      user_id: userId,
    }),
};

export default personasApi;
