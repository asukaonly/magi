import { api } from '../client';
import type { PersonalityConfig } from './personality';

export interface PersonalityPreset {
  id: string;
  name: string;
  occupation: string;
  description: string;
  avatar: string;
  prompt: string;
  group: string;
  order: number;
}

interface PersonalityPresetDetailResponse {
  success: boolean;
  message: string;
  data?: PersonalityConfig;
}

interface AvatarUploadResponse {
  filename: string;
}

const resolveApiBase = (): string =>
  (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api').replace(/\/$/, '');

export const personalitiesApi = {
  list: (lang: 'zh' | 'en' = 'zh') =>
    api.get<PersonalityPreset[]>('/personalities', { lang }),

  get: (id: string, lang: 'zh' | 'en' = 'zh') =>
    api.get<PersonalityPresetDetailResponse>(`/personalities/${id}`, { lang }),

  uploadAvatar: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<AvatarUploadResponse>('/personalities/avatar/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  getAvatarUrl: (filename?: string) =>
    filename ? `${resolveApiBase()}/personalities/avatar/${encodeURIComponent(filename)}` : '',
};

export default personalitiesApi;
