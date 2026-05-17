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

export interface PortraitPayload {
  session_id: string;
  persona_id: string;
  topic: string;
  generated_at: number;
  observations: PortraitObservation[];
  is_cold_start: boolean;
  cold_start_line: string | null;
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
