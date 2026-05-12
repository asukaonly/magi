import { api, unwrapGatewayPayload } from '../client';

export interface UserProfileProjection {
  user_id: string;
  entity_id: string;
  display_name: string;
  preferred_form_of_address: string;
  real_name: string;
  birth_date: string;
  birth_year: number | null;
  age_years: number | null;
  age_as_of: string;
  locale: string;
  timezone: string;
  home_location: string;
  communication: Record<string, unknown>;
  identity: Record<string, unknown>;
  preferences: Record<string, unknown>;
  state: Record<string, unknown>;
  field_sources: Record<string, unknown>;
  field_conflicts: Record<string, unknown>;
  completeness_score: number;
  refreshed_at: number;
  created_at: number;
  updated_at: number;
}

export interface UserProfilePatch {
  real_name?: string;
  birth_date?: string;
  preferred_form_of_address?: string;
  disallowed_forms_of_address?: string[];
  locale?: string;
  timezone?: string;
  home_location?: string;
}

export const profileApi = {
  async getMe(): Promise<UserProfileProjection> {
    const response = await api.get<UserProfileProjection>('/profile/me');
    return unwrapGatewayPayload(response);
  },

  async updateMe(patch: UserProfilePatch): Promise<UserProfileProjection> {
    const response = await api.patch<UserProfileProjection>('/profile/me', patch);
    return unwrapGatewayPayload(response);
  },

  async refreshMe(): Promise<UserProfileProjection> {
    const response = await api.post<UserProfileProjection>('/profile/me/refresh');
    return unwrapGatewayPayload(response);
  },
};