import { createContext, useContext } from 'react';
import type { ConnectionSettingsController } from '@/hooks/useConnectionSettings';

export const ConnectionSettingsContext = createContext<ConnectionSettingsController | null>(null);
export function useConnectionSettingsContext(): ConnectionSettingsController {
  const settings = useContext(ConnectionSettingsContext);
  if (!settings) throw new Error('Plugin settings require a Settings draft owner');
  return settings;
}
