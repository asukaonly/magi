import { api } from '../client';
import type { PersonalityConfig } from './personality';
import { getRuntimeConfig } from '@/runtime/config';

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
  url: string;
}

const resolveApiBase = (): string =>
  getRuntimeConfig().apiBaseUrl.replace(/\/$/, '');

const resolveBackendOrigin = (): string =>
  resolveApiBase().replace(/\/api$/, '');

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

  getAvatarUrl: (avatar?: string) => {
    if (!avatar) return '';
    if (avatar.startsWith('http://') || avatar.startsWith('https://') || avatar.startsWith('data:')) {
      return avatar;
    }
    if (avatar.startsWith('/')) {
      return `${resolveBackendOrigin()}${avatar}`;
    }
    return `${resolveBackendOrigin()}/static/avatars/${encodeURIComponent(avatar)}`;
  },
};

export default personalitiesApi;
