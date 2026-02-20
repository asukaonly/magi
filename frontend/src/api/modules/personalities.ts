import { api } from '../client';

export interface PersonalityPreset {
  id: string;
  name: string;
  description: string;
  prompt: string;
}

export interface PersonalitiesResponse {
  success: boolean;
  message: string;
  data: PersonalityPreset[];
}

export const personalitiesApi = {
  list: (lang: 'zh' | 'en' = 'zh') =>
    api.get<PersonalityPreset[]>('/personalities', { lang }),
};

export default personalitiesApi;
