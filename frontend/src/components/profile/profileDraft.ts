import type { UserProfilePatch, UserProfileProjection } from '@/api/modules/profile';

export interface ProfileDraft {
  realName: string;
  birthDate: string;
  preferredFormOfAddress: string;
  disallowedFormsOfAddress: string;
  homeLocation: string;
}

export type ProfileFieldKey = keyof ProfileDraft;

export const emptyProfileDraft: ProfileDraft = {
  realName: '',
  birthDate: '',
  preferredFormOfAddress: '',
  disallowedFormsOfAddress: '',
  homeLocation: '',
};

export function toProfileDraft(profile: UserProfileProjection | null): ProfileDraft {
  if (!profile) {
    return emptyProfileDraft;
  }
  const disallowed = profile.communication.disallowed_forms_of_address;
  return {
    realName: profile.real_name || '',
    birthDate: profile.birth_date || '',
    preferredFormOfAddress: profile.preferred_form_of_address || '',
    disallowedFormsOfAddress: Array.isArray(disallowed) ? disallowed.join(', ') : '',
    homeLocation: profile.home_location || '',
  };
}

export function toProfilePatch(draft: ProfileDraft): UserProfilePatch {
  return {
    real_name: draft.realName.trim(),
    birth_date: draft.birthDate.trim(),
    preferred_form_of_address: draft.preferredFormOfAddress.trim(),
    disallowed_forms_of_address: draft.disallowedFormsOfAddress
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
    home_location: draft.homeLocation.trim(),
  };
}

const FIELD_TO_PATCH_KEY: Record<ProfileFieldKey, keyof UserProfilePatch> = {
  realName: 'real_name',
  birthDate: 'birth_date',
  preferredFormOfAddress: 'preferred_form_of_address',
  disallowedFormsOfAddress: 'disallowed_forms_of_address',
  homeLocation: 'home_location',
};

/** Build a single-field patch for per-field inline editing. The backend
 * applies `exclude_unset`, so only the given field is touched. */
export function toProfileFieldPatch(field: ProfileFieldKey, value: string): UserProfilePatch {
  const patchKey = FIELD_TO_PATCH_KEY[field];
  const full = toProfilePatch({ ...emptyProfileDraft, [field]: value });
  return { [patchKey]: full[patchKey] };
}
