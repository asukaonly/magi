import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConnectionOnboarding } from '@/components/onboarding/ConnectionOnboarding';

const { list, pair, activate, translate, changeLanguage } = vi.hoisted(() => ({
  list: vi.fn(), pair: vi.fn(), activate: vi.fn(),
  translate: (key: string) => key, changeLanguage: vi.fn().mockResolvedValue(undefined),
}));
vi.mock('@/runtime/connections', () => ({ listConnectionProfiles: list, pairCenter: pair, activateConnection: activate, forgetConnection: vi.fn() }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translate, i18n: { changeLanguage } }) }));

const local = { id: 'local', mode: 'local' };
const remote = { id: 'remote', mode: 'remote', name: 'Home Mac', api_base_url: 'https://center.example/api' };
const profiles = (active: string | null = null, saved = false) => ({
  supports_remote: true, state: { active_profile_id: active, profiles: saved ? [local, remote] : [local] },
});
const next = () => screen.getByRole('button', { name: 'actions.next' });
async function openRemote() {
  const user = userEvent.setup();
  await waitFor(() => expect(next()).toBeEnabled());
  await user.click(screen.getByRole('radio', { name: 'location.remote.title' }));
  await user.click(next());
  return user;
}
function fillRemote() {
  for (const [label, value] of Object.entries({ address: 'https://center.example', pairingCode: 'private-code', name: 'Home', deviceName: 'Laptop' })) {
    fireEvent.change(screen.getByLabelText(`connections.${label}`), { target: { value } });
  }
}

describe('connection onboarding', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    list.mockResolvedValue(profiles());
    activate.mockResolvedValue(undefined);
    pair.mockResolvedValue(remote);
  });

  it('shows welcome before location and does not connect before an explicit choice', async () => {
    const user = userEvent.setup();
    render(<ConnectionOnboarding />);
    expect(screen.getByText('welcome.title')).toBeInTheDocument();
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('connections.address')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'welcome.getStarted' }));
    expect(screen.getByRole('heading', { name: 'location.title' })).toHaveFocus();
    expect(screen.getByRole('radio', { name: 'location.local.title' })).toBeChecked();
    expect(activate).not.toHaveBeenCalled();
    expect(pair).not.toHaveBeenCalled();
    await user.click(next());
    await waitFor(() => expect(activate).toHaveBeenCalledWith('local'));
    expect(pair).not.toHaveBeenCalled();
  });

  it('reveals only the selected remote branch and preserves the form when navigating back', async () => {
    render(<ConnectionOnboarding initialStep="location" />);
    const user = await openRemote();
    expect(screen.getByRole('heading', { name: 'location.remoteTitle' })).toHaveFocus();
    expect(screen.queryByText('steps.llmSetup')).not.toBeInTheDocument();
    fillRemote();
    await user.click(screen.getByRole('button', { name: 'actions.previous' }));
    expect(screen.queryByLabelText('connections.address')).not.toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'location.remote.title' })).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'actions.previous' }));
    expect(screen.getByRole('heading', { name: 'welcome.title' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'welcome.getStarted' }));
    expect(screen.getByRole('radio', { name: 'location.remote.title' })).toBeChecked();
    await user.click(next());
    expect(screen.getByLabelText('connections.address')).toHaveValue('https://center.example');
    expect(screen.getByLabelText('connections.pairingCode')).toHaveValue('private-code');
    expect(localStorage.length).toBe(0);
  });

  it('pairs before activation and keeps connection credentials out of browser storage', async () => {
    render(<ConnectionOnboarding initialStep="location" />);
    const user = await openRemote();
    fillRemote();
    await user.click(screen.getByRole('button', { name: 'connections.pair' }));
    await waitFor(() => expect(activate).toHaveBeenCalledWith('remote'));
    expect(pair).toHaveBeenCalledWith('https://center.example', 'private-code', 'Home', 'Laptop');
    expect(pair.mock.invocationCallOrder[0]).toBeLessThan(activate.mock.invocationCallOrder[0]);
    expect(localStorage.length).toBe(0);
    expect(screen.getByLabelText('connections.pairingCode')).toHaveValue('');
  });

  it('keeps failed native pairings editable with their original inputs', async () => {
    pair.mockRejectedValue('Pairing expired');
    render(<ConnectionOnboarding initialStep="location" />);
    const user = await openRemote();
    fillRemote();
    await user.click(screen.getByRole('button', { name: 'connections.pair' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Pairing expired');
    expect(screen.getByLabelText('connections.pairingCode')).toHaveValue('private-code');
    expect(screen.getByLabelText('connections.address')).toBeEnabled();
    expect(activate).not.toHaveBeenCalled();
  });

  it('owns a single pairing request and blocks back navigation while it is pending', async () => {
    let finish!: (value: typeof remote) => void;
    pair.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    render(<ConnectionOnboarding initialStep="location" />);
    await openRemote();
    fillRemote();
    const form = screen.getByLabelText('connections.address').closest('form')!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(pair).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'actions.previous' })).toBeDisabled();
    await act(async () => finish(remote));
    await waitFor(() => expect(activate).toHaveBeenCalledWith('remote'));
  });

  it('does not activate a pairing that finishes after this flow unmounts', async () => {
    let finish!: (value: typeof remote) => void;
    pair.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const view = render(<ConnectionOnboarding initialStep="location" />);
    await openRemote();
    fillRemote();
    fireEvent.submit(screen.getByLabelText('connections.address').closest('form')!);
    view.unmount();
    await act(async () => finish(remote));
    expect(activate).not.toHaveBeenCalled();
  });

  it('reuses a saved remote center without requiring another pairing code', async () => {
    list.mockResolvedValue(profiles(null, true));
    render(<ConnectionOnboarding initialStep="location" />);
    const user = await openRemote();
    await user.click(screen.getByRole('button', { name: 'connections.connect' }));
    await waitFor(() => expect(activate).toHaveBeenCalledWith('remote'));
    expect(pair).not.toHaveBeenCalled();
  });

  it('offers the saved profile when pairing succeeds but activation fails', async () => {
    activate.mockRejectedValueOnce(new Error('Center temporarily unavailable'));
    render(<ConnectionOnboarding initialStep="location" />);
    const user = await openRemote();
    fillRemote();
    list.mockResolvedValue(profiles(null, true));
    await user.click(screen.getByRole('button', { name: 'connections.pair' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Center temporarily unavailable');
    expect(screen.getByLabelText('connections.pairingCode')).toHaveValue('');
    await user.click(await screen.findByRole('button', { name: 'connections.connect' }));
    await waitFor(() => expect(activate).toHaveBeenCalledTimes(2));
    expect(pair).toHaveBeenCalledTimes(1);
  });

  it('returns to unfinished setup when its current center is selected again', async () => {
    list.mockResolvedValue(profiles('local'));
    const resume = vi.fn();
    render(<ConnectionOnboarding initialStep="location" onUseActive={resume} />);
    await waitFor(() => expect(next()).toBeEnabled());
    fireEvent.click(next());
    expect(resume).toHaveBeenCalledTimes(1);
    expect(activate).not.toHaveBeenCalled();
  });

  it('retries an active center from startup recovery instead of only closing the picker', async () => {
    list.mockResolvedValue(profiles('local'));
    const back = vi.fn();
    render(<ConnectionOnboarding initialStep="location" onBack={back} />);
    await waitFor(() => expect(next()).toBeEnabled());
    fireEvent.click(next());
    await waitFor(() => expect(activate).toHaveBeenCalledWith('local'));
    expect(back).not.toHaveBeenCalled();
  });

  it('allows retry after profile loading fails without assuming a local connection', async () => {
    list.mockRejectedValueOnce(new Error('Unavailable'));
    render(<ConnectionOnboarding initialStep="location" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('connections.loadFailed');
    expect(next()).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }));
    await waitFor(() => expect(next()).toBeEnabled());
    expect(activate).not.toHaveBeenCalled();
  });

  it('changes the device language from welcome before contacting a center', async () => {
    render(<ConnectionOnboarding />);
    fireEvent.click(screen.getByRole('button', { name: 'EN' }));
    expect(localStorage.getItem('magi_language')).toBe('en');
    expect(document.documentElement.lang).toBe('en');
    expect(changeLanguage).toHaveBeenCalledWith('en');
    expect(activate).not.toHaveBeenCalled();
    expect(pair).not.toHaveBeenCalled();
  });
});
