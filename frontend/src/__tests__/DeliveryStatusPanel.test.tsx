import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { DeliveryStatusPanel } from '@/components/settings/DeliveryStatusPanel';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { resolvedLanguage: 'en' } }),
}));
vi.mock('@/api/modules/channelEndpoints', () => ({
  channelEndpointsApi: { status: vi.fn(async () => [{
    delivery_id: 'audio', message_id: 'message', session_id: 'session',
    endpoint: { connection_id: 'house', contribution_id: 'speaker', target_id: 'Kitchen', thread_id: null, device_id: null },
    state: 'succeeded', playback_state: 'accepted', attempt_count: 1, updated_at_ms: 1000,
  }]) },
}));

it('shows accepted playback without claiming that audio completed', async () => {
  render(<DeliveryStatusPanel />);
  expect(await screen.findByText('settings.deliveryStatus.playback.accepted')).toBeInTheDocument();
  expect(screen.queryByText('settings.deliveryStatus.playback.completed')).not.toBeInTheDocument();
  expect(screen.queryByText('settings.deliveryStatus.states.succeeded')).not.toBeInTheDocument();
});
