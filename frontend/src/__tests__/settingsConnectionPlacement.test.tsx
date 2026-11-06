import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { SettingsConnectionsSection } from '@/components/settings/SettingsConnectionsSection';
import { SettingsPreferencesSection } from '@/components/settings/SettingsPreferencesSection';
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/components/connections/ConnectionPicker', () => ({ ConnectionPicker: () => <p>Saved connections</p> }));
vi.mock('@/components/connections/CenterAccessPanel', () => ({ CenterAccessPanel: () => <p>Device access</p> }));
vi.mock('@/components/connections/BackgroundDeliveryPanel', () => ({ BackgroundDeliveryPanel: () => <p>Sync diagnostics</p> }));
vi.mock('@/components/connections/CenterNotificationPolicy', () => ({ CenterNotificationPolicy: () => <p>Multi-device alerts</p> }));

it('keeps connection management focused and places notifications and sync with their owning settings', () => {
  const view = render(<SettingsConnectionsSection hasUnsavedSettings={false} />);
  expect(screen.getByText('Saved connections')).toBeInTheDocument();
  expect(screen.getByText('Device access')).toBeInTheDocument();
  expect(screen.queryByText('Sync diagnostics')).not.toBeInTheDocument();
  expect(screen.queryByText('Multi-device alerts')).not.toBeInTheDocument();
  const props = { draftConfig: structuredClone(DEFAULT_SYSTEM_CONFIG), fakeIpCompatibilityEnabled: false,
    onFakeIpCompatibilityChange: vi.fn(), draftThemeMode: 'light' as const, patchDraftConfig: vi.fn(), onThemePreviewChange: vi.fn(), onLanguageDraftChange: vi.fn() };
  view.rerender(<SettingsPreferencesSection {...props} section="desktop" />);
  expect(screen.getByText('Multi-device alerts')).toBeInTheDocument();
  expect(screen.getByRole('switch', { name: 'settings.desktopNotificationsLabel' })).toBeInTheDocument();
  expect(screen.queryByText('Sync diagnostics')).not.toBeInTheDocument();
  view.rerender(<SettingsPreferencesSection {...props} section="diagnostics" />);
  expect(screen.getByText('Sync diagnostics')).toBeInTheDocument();
  expect(screen.queryByText('Multi-device alerts')).not.toBeInTheDocument();
});
