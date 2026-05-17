import { api, unwrapGatewayPayload } from '../client';

export type PortraitObservationKind =
  | 'reflection'
  | 'assertion'
  | 'relationship'
  | 'procedure';

export interface PortraitObservation {
  kind: PortraitObservationKind;
  text: string;
  basis_count: number;
  basis_summary: string;
  basis_refs: string[];
}

export type ColdStartReason =
  | 'no_persona'
  | 'no_messages'
  | 'topic_empty'
  | 'no_snippets'
  | 'no_observations'
  | 'computing';

export interface PortraitPayload {
  session_id: string;
  persona_id: string;
  topic: string;
  generated_at: number;
  observations: PortraitObservation[];
  is_cold_start: boolean;
  cold_start_line: string | null;
  cold_start_reason: ColdStartReason | null;
  /**
   * True when the backend served a previously-cached payload past its TTL
   * while a fresh recompute is in flight. UI should keep showing the
   * existing observations; the hook continues polling until a fresh
   * (is_stale=false) payload arrives.
   */
  is_stale: boolean;
}

export const memoryPortraitApi = {
  get: async (
    sessionId: string,
    userId: string,
    options?: { force?: boolean },
  ): Promise<PortraitPayload> => {
    const response = await api.get<PortraitPayload>('/memory/portrait', {
      params: {
        session_id: sessionId,
        user_id: userId,
        force: options?.force ? 'true' : 'false',
      },
    });
    return unwrapGatewayPayload(response);
  },
};
