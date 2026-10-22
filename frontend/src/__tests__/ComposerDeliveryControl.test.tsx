import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ComposerDeliveryControl } from '@/components/chat/ComposerDeliveryControl';
import { channelEndpointsApi, type EndpointRef } from '@/api/modules/channelEndpoints';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/api/modules/channelEndpoints', async importOriginal => ({
  ...await importOriginal<typeof import('@/api/modules/channelEndpoints')>(),
  channelEndpointsApi: { list: vi.fn() },
}));
const endpoint: EndpointRef = {
  connection_id: 'home', contribution_id: 'message', target_id: 'kitchen',
  thread_id: null, device_id: null,
};
function Harness() {
  const [value, setValue] = useState<EndpointRef[] | null>(null);
  return <><ComposerDeliveryControl value={value} onChange={setValue} />
    <output data-testid="selection">{JSON.stringify(value)}</output></>;
}
describe('ComposerDeliveryControl', () => {
  beforeEach(() => {
    vi.mocked(channelEndpointsApi.list).mockReset().mockResolvedValue([
      { endpoint, label: 'Kitchen', available: false, capabilities: ['message'] },
    ]);
  });
  it('distinguishes defaults, explicit targets and no additional targets', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const open = () => user.click(screen.getByRole('button', { name: 'chat.delivery.controlLabel' }));
    await open();
    await user.click(await screen.findByRole('menuitemcheckbox', { name: /Kitchen/ }));
    expect(screen.getByTestId('selection')).toHaveTextContent(JSON.stringify([endpoint]));
    await user.click(screen.getByRole('menuitem', { name: 'chat.delivery.current' }));
    expect(screen.getByTestId('selection')).toHaveTextContent('[]');
    await open();
    await user.click(screen.getByRole('menuitem', { name: 'chat.delivery.default' }));
    expect(screen.getByTestId('selection')).toHaveTextContent('null');
  });
  it('retries discovery failures without discarding a selection', async () => {
    vi.mocked(channelEndpointsApi.list).mockRejectedValueOnce(new Error('offline'));
    const user = userEvent.setup();
    render(<ComposerDeliveryControl value={[endpoint]} onChange={vi.fn()} />);
    await user.click(screen.getByRole('button'));
    await user.click(await screen.findByText('chat.delivery.retry'));
    expect(await screen.findByRole('menuitemcheckbox', { name: /Kitchen/ })).toHaveAttribute('aria-checked', 'true');
    await waitFor(() => expect(channelEndpointsApi.list).toHaveBeenCalledTimes(2));
  });
  it('aborts discovery when the composer becomes unavailable', async () => {
    vi.mocked(channelEndpointsApi.list).mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    const { rerender } = render(<ComposerDeliveryControl value={null} onChange={vi.fn()} />);
    await user.click(screen.getByRole('button'));
    const signal = vi.mocked(channelEndpointsApi.list).mock.calls[0]?.[0];
    rerender(<ComposerDeliveryControl value={null} onChange={vi.fn()} disabled />);
    expect(signal?.aborted).toBe(true);
    expect(screen.getByRole('button')).toBeDisabled();
  });
  it('lets an audio-only endpoint receive an explicit reply', async () => {
    vi.mocked(channelEndpointsApi.list).mockResolvedValue([
      { endpoint, label: 'Speaker', available: true, capabilities: ['audio'] },
    ]);
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole('button'));
    await user.click(await screen.findByRole('menuitemcheckbox', { name: /Speaker/ }));
    expect(screen.getByTestId('selection')).toHaveTextContent(JSON.stringify([endpoint]));
  });
});
