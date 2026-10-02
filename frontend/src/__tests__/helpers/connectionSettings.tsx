import { render, type RenderOptions } from '@testing-library/react';
import { useState, type ReactElement, type ReactNode } from 'react';
import { useConnectionSettings } from '@/hooks/useConnectionSettings';
import { ConnectionSettingsContext } from '@/components/settings/ConnectionSettingsContext';

export function ConnectionSettingsHarness({ children }: { children: ReactNode }) {
  const settings = useConnectionSettings();
  const [error, setError] = useState('');
  return <ConnectionSettingsContext.Provider value={settings}>
    {children}
    <footer>
      <span>{settings.dirty ? 'Unsaved changes' : 'All changes saved'}</span>
      <button disabled={!settings.dirty || settings.saving} onClick={() => settings.discard()}>Discard</button>
      <button disabled={!settings.dirty || settings.saving} onClick={() => { void settings.save().catch(failure => setError(String(failure))); }}>Save settings</button>
      {error ? <p role="alert">{error}</p> : null}
    </footer>
  </ConnectionSettingsContext.Provider>;
}
export const renderWithConnectionSettings = (ui: ReactElement, options?: RenderOptions) => render(ui, { wrapper: ConnectionSettingsHarness, ...options });
