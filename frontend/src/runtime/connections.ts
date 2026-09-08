import { invoke } from '@tauri-apps/api/core';
import { z } from 'zod';
import { advanceBrowserContentGeneration } from '@/lib/browserContentGeneration';
import { resetRuntimeInitialization } from './config';

const profileSchema = z.discriminatedUnion('mode', [
  z.object({ mode: z.literal('local'), id: z.literal('local') }),
  z.object({ mode: z.literal('remote'), id: z.string().uuid(), name: z.string(), api_base_url: z.string().url(), server_id: z.string().uuid(), client_id: z.string().uuid() }),
]);
const profilesSchema = z.object({
  state: z.object({ version: z.literal(1), active_profile_id: z.string().nullable(), profiles: z.array(profileSchema).max(17) }),
  supports_remote: z.boolean(),
});
export type ConnectionProfiles = z.infer<typeof profilesSchema>;
export type ConnectionProfile = z.infer<typeof profileSchema>;

export async function listConnectionProfiles(): Promise<ConnectionProfiles> {
  return profilesSchema.parse(await invoke<unknown>('list_connection_profiles'));
}
export async function pairCenter(address: string, pairingToken: string, name: string): Promise<ConnectionProfile> {
  return profileSchema.parse(await invoke<unknown>('pair_center', { address, pairingToken, name }));
}
export async function activateConnection(profileId: string): Promise<void> {
  await invoke('select_connection_profile', { profileId });
  advanceBrowserContentGeneration();
  resetRuntimeInitialization();
  window.location.replace('/');
}
export async function forgetConnection(profileId: string): Promise<void> {
  await invoke('forget_connection_profile', { profileId });
}
