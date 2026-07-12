/**
 * Persona registry API – wraps /api/personas/* endpoints.
 *
 * All persona CRUD, active-persona management, seed previews, and seeding
 * are routed through UUID-keyed persona registry.
 */
import { api, unwrapGatewayPayload } from '../client';
import type { LLMConfig } from './config';
import { getRuntimeConfig } from '@/runtime/config';

// ---------------------------------------------------------------------------
// Personality config types (schema of a persona's `config` field)
// ---------------------------------------------------------------------------

export interface IdentityCore {
  identity_statement: string;
  values_loved: string[];
  values_rejected: string[];
  attention_biases: string[];
}

export interface Idiolect {
  sentence_style: string;
  vocab_available: string[];
  vocab_avoided: string[];
  structural_quirks: string[];
}

export interface PersonaRegister {
  description: string;
  behavior: string;
  examples: string[];
}

export interface SignatureTrigger {
  trigger_id: string;
  activates_when: string;
  behavior_shift: string;
  intensity_levels: Record<string, string>;
  exit_behavior: string;
}

export interface QuietHour {
  condition: string;
  clamps: Record<string, unknown>;
}

export const LAYER_MODIFIER_KEYS = [
  'behavior_shifts',
  'memory_behavior',
  'protective_bias',
  'voice_unlocks',
  'humor_delta',
  'directness_delta',
  'register_unlocks',
  'trigger_threshold_shifts',
  'sarcasm_bounds',
] as const;

export type LayerModifierKey = (typeof LAYER_MODIFIER_KEYS)[number];

export interface LayerModifiers {
  behavior_shifts?: string[];
  memory_behavior?: string;
  protective_bias?: string;
  voice_unlocks?: string[];
  humor_delta?: number;
  directness_delta?: number;
  register_unlocks?: string[];
  trigger_threshold_shifts?: Record<string, number>;
  sarcasm_bounds?: string;
}

export interface PersonaLayerItem {
  layer_id: string;
  unlock_condition: Record<string, unknown> | null;
  modifiers: LayerModifiers;
}

export interface BootstrapConfig {
  style_instruction: string;
  opening_line: string;
  max_rounds: number;
}

export interface PersonalityConfig {
  name: string;
  avatar: string;
  description: string;
  appearance_prompt: string;
  identity_core: IdentityCore;
  idiolect: Idiolect;
  registers: Record<string, PersonaRegister>;
  quiet_hours: QuietHour[];
  signature_triggers: SignatureTrigger[];
  persona_layers: PersonaLayerItem[];
  dynamic_state_rules: Record<string, string>;
  milestone_conditions: Record<string, string>;
  interim_lines: Record<string, string[]>;
  bootstrap: BootstrapConfig | null;
}

export interface AIGenerateRequest {
  description: string;
  target_language?: string;
  current_config?: PersonalityConfig;
  llm_override?: LLMConfig;
}

export const PERSONA_GENERATION_STAGE_IDS = [
  'base',
  'registers',
  'rules',
  'layers',
  'bootstrap',
  'appearance',
  'integrate',
] as const;

export type PersonaGenerationStageId = (typeof PERSONA_GENERATION_STAGE_IDS)[number];

export interface PersonaGenerationStage {
  stage_id: PersonaGenerationStageId | string;
  label?: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
}

export interface PersonalityGenerateResponse {
  success: boolean;
  message: string;
  data?: PersonalityConfig;
  stages?: PersonaGenerationStage[];
}

export interface PersonalityGenerationJobSnapshot {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  stages: PersonaGenerationStage[];
  created_at?: number;
  updated_at?: number;
  data?: PersonalityConfig;
  error?: string;
}

export interface PersonalityGenerationJobResponse {
  success: boolean;
  message: string;
  data?: PersonalityGenerationJobSnapshot;
  stages?: PersonaGenerationStage[];
}

export type PersonalityGenerationProgressCallback = (snapshot: PersonalityGenerationJobSnapshot) => void;

const GENERATION_JOB_POLL_MS = 1000;
const GENERATION_JOB_TIMEOUT_MS = 600000;

const wait = (ms: number): Promise<void> => new Promise((resolve) => window.setTimeout(resolve, ms));
const AVATAR_IMAGE_FILENAME_RE = /\.(?:avif|gif|jpe?g|png|svg|webp)$/i;

// ---------------------------------------------------------------------------
// Personality config defaults
// ---------------------------------------------------------------------------

export const DEFAULT_IDENTITY_CORE: IdentityCore = {
  identity_statement: '',
  values_loved: [],
  values_rejected: [],
  attention_biases: [],
};

export const DEFAULT_IDIOLECT: Idiolect = {
  sentence_style: '',
  vocab_available: [],
  vocab_avoided: [],
  structural_quirks: [],
};

export const DEFAULT_SIGNATURE_TRIGGERS: SignatureTrigger[] = [
  {
    trigger_id: '',
    activates_when: '',
    behavior_shift: '',
    intensity_levels: {},
    exit_behavior: '',
  },
];

export const DEFAULT_PERSONALITY_CONFIG: PersonalityConfig = {
  name: 'AI Assistant',
  avatar: '',
  description: '',
  appearance_prompt: '',
  identity_core: DEFAULT_IDENTITY_CORE,
  idiolect: DEFAULT_IDIOLECT,
  registers: {
    chat: { description: '', behavior: '', examples: [] },
    analysis: { description: '', behavior: '', examples: [] },
    task: { description: '', behavior: '', examples: [] },
    emotional: { description: '', behavior: '', examples: [] },
    crisis: { description: '', behavior: '', examples: [] },
  },
  quiet_hours: [],
  signature_triggers: DEFAULT_SIGNATURE_TRIGGERS,
  persona_layers: [{ layer_id: 'surface', unlock_condition: null, modifiers: {} }],
  dynamic_state_rules: {},
  milestone_conditions: {},
  interim_lines: {},
  bootstrap: null,
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
  seed_slug?: string | null;
  description: string;
  deleted_at?: number | null;
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
  deleted_at?: number | null;
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
  default?: boolean;
  recommended?: boolean;
  is_default?: boolean;
  is_recommended?: boolean;
}

export interface SeedPreviewResponse {
  success: boolean;
  data: SeedPreview[];
}

export interface SeedResponse {
  success: boolean;
  created_ids: string[];
}

export interface ActivePersonaResponse {
  success: boolean;
  persona_id: string | null;
}

export const selectDefaultSeedPreview = (previews: SeedPreview[]): SeedPreview | undefined =>
  [...previews].sort((left, right) => {
    const leftMarked = left.default || left.recommended || left.is_default || left.is_recommended;
    const rightMarked = right.default || right.recommended || right.is_default || right.is_recommended;
    if (Boolean(leftMarked) !== Boolean(rightMarked)) {
      return leftMarked ? -1 : 1;
    }
    if (left.order !== right.order) {
      return left.order - right.order;
    }
    return left.name.localeCompare(right.name);
  })[0];

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

export const personasApi = {
  /** List all registered personas. */
  list: (options?: { includeDeleted?: boolean }) => api.get<PersonaSummary[]>('/personas/', {
    params: options?.includeDeleted ? { include_deleted: true } : undefined,
  }),

  /** Get full detail for a persona by ID. */
  get: (personaId: string, options?: { includeDeleted?: boolean }) => api.get<PersonaDetail>(
    '/personas/' + personaId,
    options?.includeDeleted ? { params: { include_deleted: true } } : undefined,
  ),

  /** Create a new custom persona. Returns detail including assigned persona_id. */
  create: (payload: {
    persona_id?: string;
    config_json: string;
    locale?: string;
    slug?: string;
  }) =>
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
  getActive: async (): Promise<ActivePersonaResponse> =>
    unwrapGatewayPayload(await api.get<ActivePersonaResponse>('/personas/active')),

  /** Switch the active persona. Returns persona_id at the top level. */
  setActive: async (personaId: string): Promise<ActivePersonaResponse> =>
    unwrapGatewayPayload(await api.put<ActivePersonaResponse>('/personas/active', { persona_id: personaId })),

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
    const value = (avatar || '').trim();
    if (!value) return '';
    if (value.startsWith('http://') || value.startsWith('https://') || value.startsWith('data:image/')) {
      return value;
    }
    const origin = getRuntimeConfig().apiBaseUrl.replace(/\/api$/, '');
    if (value.startsWith('/')) return `${origin}${value}`;
    if (!AVATAR_IMAGE_FILENAME_RE.test(value)) return '';
    return `${origin}/static/avatars/${encodeURIComponent(value)}`;
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
  // Personality generation & bootstrap
  // -----------------------------------------------------------------------

  /** AI-generate a personality config from a description. */
  generate: (request: AIGenerateRequest) =>
    api.post<PersonalityConfig>('/personality/generate', request, {
      timeout: GENERATION_JOB_TIMEOUT_MS,
    }) as Promise<PersonalityGenerateResponse>,

  /** Start AI personality generation as a background job. */
  startGenerationJob: (request: AIGenerateRequest) =>
    api.post<PersonalityGenerationJobSnapshot>('/personality/generation-jobs', request, {
      timeout: 20000,
    }) as Promise<PersonalityGenerationJobResponse>,

  /** Poll AI personality generation status. */
  getGenerationJob: (jobId: string) =>
    api.get<PersonalityGenerationJobSnapshot>(`/personality/generation-jobs/${jobId}`, {
      timeout: 20000,
    }) as Promise<PersonalityGenerationJobResponse>,

  /** AI-generate a personality config with real backend stage progress. */
  generateWithProgress: async (
    request: AIGenerateRequest,
    onProgress?: PersonalityGenerationProgressCallback,
  ): Promise<PersonalityGenerateResponse> => {
    const started = await personasApi.startGenerationJob(request);
    let snapshot = started.data;
    if (!snapshot?.job_id) {
      throw new Error('Personality generation job did not start');
    }
    onProgress?.(snapshot);

    const startedAt = Date.now();
    while (snapshot.status !== 'completed' && snapshot.status !== 'failed') {
      if (Date.now() - startedAt > GENERATION_JOB_TIMEOUT_MS) {
        throw new Error('Personality generation timed out');
      }
      await wait(GENERATION_JOB_POLL_MS);
      const polled = await personasApi.getGenerationJob(snapshot.job_id);
      if (!polled.data) {
        throw new Error('Personality generation job status is unavailable');
      }
      snapshot = polled.data;
      onProgress?.(snapshot);
    }

    if (snapshot.status === 'failed') {
      throw new Error(snapshot.error || 'Personality generation failed');
    }
    if (!snapshot.data) {
      throw new Error('Personality generation completed without a result');
    }
    return {
      success: true,
      message: 'AI personality configuration generated successfully',
      data: snapshot.data,
      stages: snapshot.stages,
    };
  },

  /** Get a greeting from the active persona. */
  getGreeting: () =>
    api.get<{
      name: string;
      avatar?: string;
      needs_bootstrap?: boolean;
      needs_bootstrap_init?: boolean;
      bootstrap_completed?: boolean;
    }>('/personality/greeting'),

  /** Init a bootstrap session for the active persona. */
  bootstrapInit: (sessionId: string, userId: string = 'default_user') =>
    api.post<{
      bootstrap_active: boolean;
      opening: string | null;
      startup_state?: string;
      deferred_reason?: string | null;
    }>('/personality/bootstrap/init', {
      session_id: sessionId,
      user_id: userId,
    }, {
      timeout: 20000,
    }),
};

export default personasApi;
