import { apiClient } from '../client';

export interface SkillItem {
  name: string;
  description: string;
  category?: string;
  argument_hint?: string;
  user_invocable: boolean;
  context?: string;
  agent?: string;
  tags: string[];
  directory: string;
  enabled?: boolean;
}

export const skillsApi = {
  list: () => apiClient.get<SkillItem[]>('/skills/').then((res) => res.data),
};

export default skillsApi;
