import { apiClient } from '../client';

export interface HookEntry {
  event_type: string;
  matcher: string | null;
  source: string | null;
}

export interface HooksListResponse {
  total: number;
  entries: HookEntry[];
}

export const hooksApi = {
  list: () =>
    apiClient.get<HooksListResponse>('/hooks').then((res) => res.data),
};

export default hooksApi;
