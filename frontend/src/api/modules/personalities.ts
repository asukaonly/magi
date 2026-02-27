import { api } from '../client';

export interface PersonalityPreset {
  id: string;
  name: string;
  occupation: string;
  description: string;
  prompt: string;
}

export const personalitiesApi = {
  list: (lang: 'zh' | 'en' = 'zh') =>
    api.get<PersonalityPreset[]>('/personalities', { lang }),
};

export default personalitiesApi;
