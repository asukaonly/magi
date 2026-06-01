import { api, unwrapGatewayPayload } from '../client';
import type { PortraitPayload } from './memoryPortrait';

export const memoryPortraitSelfApi = {
  get: async (userId: string): Promise<PortraitPayload> => {
    const response = await api.get<PortraitPayload>('/memory/portrait/self', {
      params: { user_id: userId },
    });
    return unwrapGatewayPayload(response);
  },
};
