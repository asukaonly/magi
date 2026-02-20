import { api } from '../client';

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
  list: () => api.get<SkillItem[]>('/skills'),
};

export default skillsApi;
