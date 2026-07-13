import { api, unwrapGatewayPayload } from '../client';

export type SelfPortraitObservationKind =
  | 'reflection'
  | 'assertion'
  | 'relationship'
  | 'procedure';

export interface SelfPortraitObservation {
  kind: SelfPortraitObservationKind;
  text: string;
  basis_count: number;
  basis_summary: string;
  basis_refs: string[];
}

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
  session_id: string;
  persona_id: string;
  topic: string;
  generated_at: number;
  observations: SelfPortraitObservation[];
  self_view?: PortraitSelfView | null;
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
