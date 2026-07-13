import { api, unwrapGatewayPayload } from '../client';

export type PortraitSelfViewWorldGroupId =
  | 'identity'
  | 'projects'
  | 'preferences'
  | 'work_style';

export interface PortraitSelfViewItem {
  id: string;
  text: string;
  source: string;
  source_key: string | null;
  assertion_id: string | null;
  basis_count: number;
  basis_refs: string[];
  claim_kind?:
    | 'identity_fact'
    | 'active_work'
    | 'preference_interest'
    | 'collaboration_style'
    | 'recent_context'
    | 'inventory_signal'
    | null;
}

export interface PortraitSelfViewWorldGroup {
  id: PortraitSelfViewWorldGroupId;
  summary?: string;
  items: PortraitSelfViewItem[];
}

export interface PortraitSelfView {
  world: {
    total_count: number;
    groups: PortraitSelfViewWorldGroup[];
  };
  review: {
    items: PortraitSelfViewItem[];
  };
  recent: {
    items: PortraitSelfViewItem[];
  };
}

export interface SelfPortraitPayload {
  generated_at: number;
  self_view: PortraitSelfView;
  is_cold_start: boolean;
  cold_start_line: string | null;
  cold_start_reason: string | null;
  is_stale: boolean;
}

export const memoryPortraitSelfApi = {
  get: async (userId: string): Promise<SelfPortraitPayload> => {
    const response = await api.get<SelfPortraitPayload>('/memory/portrait/self', {
      params: { user_id: userId },
    });
    return unwrapGatewayPayload(response);
  },
};
