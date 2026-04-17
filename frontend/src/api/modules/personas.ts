/**
 * Persona registry API – wraps /api/personas/* endpoints.
 *
 * All persona CRUD, active-persona management, seed previews, and seeding
 * are routed through UUID-keyed persona registry.
 */
import { api } from '../client';

// ---------------------------------------------------------------------------
// Types
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
};

export default personasApi;
