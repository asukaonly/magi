import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fixtures from '../../../contracts/api/frontend-config-examples.json';
import { api } from '@/api/client';
import { codeAgentApi, type SettingsResponse, type ProbeResponse } from '@/api/modules/codeAgent';
import { validateCodeAgentSettingsResponse, validateCodeAgentProbeResponse } from '@/api/generated/config-validators';
import { CodeAgentSection } from '@/components/settings/CodeAgentSection';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const settingsFixture: unknown = fixtures.codeAgentSettings;
const probeFixture: unknown = fixtures.codeAgentProbe;
if (!validateCodeAgentSettingsResponse(settingsFixture) || !validateCodeAgentProbeResponse(probeFixture)) throw new Error('Invalid production fixture');
const settings: SettingsResponse = settingsFixture;
const probe: ProbeResponse = probeFixture;

afterEach(() => vi.restoreAllMocks());

describe('code tool API contract', () => {
  it('uses production models and rejects invalid settings and incomplete probes', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue(settings as never);
    expect(await codeAgentApi.getSettings(null)).toEqual(settings);
    get.mockResolvedValue({ success: true, data: settings } as never);
    await expect(codeAgentApi.getSettings(null)).rejects.toThrow();
    get.mockResolvedValue({ ...settings, settings: { ...settings.settings, enabled: 'yes' } } as never);
    await expect(codeAgentApi.getSettings(null)).rejects.toThrow();
    get.mockResolvedValue(probe as never);
    expect(await codeAgentApi.probe()).toEqual(probe);
    get.mockResolvedValue({ results: { codex: probe.results.codex } } as never);
    await expect(codeAgentApi.probe()).rejects.toThrow();
  });
});

describe('code tool settings drafts', () => {
  beforeEach(() => {
    vi.spyOn(codeAgentApi, 'getSettings').mockResolvedValue(structuredClone(settings));
    vi.spyOn(codeAgentApi, 'probe').mockResolvedValue(structuredClone(probe));
    vi.spyOn(codeAgentApi, 'patchSettings').mockResolvedValue(structuredClone(settings));
  });

  it('keeps the original draft revision during refresh and reloads explicitly after conflict', async () => {
    const user = userEvent.setup();
    render(<CodeAgentSection />);
    const timeout = await screen.findByLabelText('settings.codeAgent.defaultTimeout');
    await user.clear(timeout);
    await user.type(timeout, '120');
    const updated = { ...settings, revision: 'b'.repeat(64), settings: { ...settings.settings, constraints: { ...settings.settings.constraints, default_timeout_s: 180 } } };
    vi.mocked(codeAgentApi.getSettings).mockResolvedValue(updated);
    act(() => { window.dispatchEvent(new Event('focus')); });
    await waitFor(() => expect(codeAgentApi.getSettings).toHaveBeenCalledTimes(2));
    expect(timeout).toHaveValue(120);
    vi.mocked(codeAgentApi.patchSettings).mockRejectedValueOnce({ status: 409 });
    await user.click(screen.getByRole('button', { name: 'common.save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('settings.centerConflict');
    expect(timeout).toHaveValue(120);
    expect(codeAgentApi.patchSettings).toHaveBeenCalledWith('user', expect.anything(), null, settings.revision);
    expect(screen.getByRole('button', { name: 'common.save' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'settings.reloadCenterConfig' }));
    const reloaded = await screen.findByLabelText('settings.codeAgent.defaultTimeout');
    expect(reloaded).toHaveValue(180);
    await user.clear(reloaded);
    await user.type(reloaded, '240');
    vi.mocked(codeAgentApi.patchSettings).mockResolvedValueOnce(updated);
    await user.click(screen.getByRole('button', { name: 'common.save' }));
    await waitFor(() => expect(codeAgentApi.patchSettings).toHaveBeenLastCalledWith('user', expect.anything(), null, updated.revision));
  });

  it('ignores a delayed read after accepting its own save receipt', async () => {
    const user = userEvent.setup();
    render(<CodeAgentSection />);
    const timeout = await screen.findByLabelText('settings.codeAgent.defaultTimeout');
    let resolve!: (snapshot: SettingsResponse) => void;
    vi.mocked(codeAgentApi.getSettings).mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    act(() => { window.dispatchEvent(new Event('focus')); });
    await waitFor(() => expect(codeAgentApi.getSettings).toHaveBeenCalledTimes(2));
    await user.clear(timeout);
    await user.type(timeout, '120');
    const accepted = { ...settings, revision: 'b'.repeat(64), settings: { ...settings.settings, constraints: { ...settings.settings.constraints, default_timeout_s: 120 } } };
    vi.mocked(codeAgentApi.patchSettings).mockResolvedValueOnce(accepted);
    await user.click(screen.getByRole('button', { name: 'common.save' }));
    await screen.findByText('settings.codeAgent.saved');
    await act(async () => { resolve(settings); });
    expect(timeout).toHaveValue(120);
    expect(screen.getByRole('button', { name: 'common.save' })).toBeDisabled();
  });

  it('shows a failed initial load and recovers through retry', async () => {
    vi.mocked(codeAgentApi.getSettings).mockRejectedValueOnce(new Error('Offline'));
    const user = userEvent.setup();
    render(<CodeAgentSection />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Offline');
    expect(screen.queryByText('settings.codeAgent.loading')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'common.retry' }));
    expect(await screen.findByLabelText('settings.codeAgent.defaultTimeout')).toHaveValue(600);
    expect(codeAgentApi.getSettings).toHaveBeenLastCalledWith(null);
  });

  it('retains typed drafts on rejection, prevents blank timeouts and accepts canonical save results', async () => {
    const user = userEvent.setup();
    render(<CodeAgentSection />);
    const timeout = await screen.findByLabelText('settings.codeAgent.defaultTimeout');
    const model = screen.getAllByLabelText('settings.codeAgent.defaultModel')[0];
    await user.type(model, 'local-draft');
    await user.clear(timeout);
    expect(timeout).toHaveValue(null);
    expect(screen.getByRole('alert')).toHaveTextContent('settings.codeAgent.invalidTimeout');
    expect(screen.getByRole('button', { name: 'common.save' })).toBeDisabled();
    expect(codeAgentApi.patchSettings).not.toHaveBeenCalled();
    await user.type(timeout, '120');
    vi.mocked(codeAgentApi.patchSettings).mockRejectedValueOnce(new Error('Write failed'));
    await user.click(screen.getByRole('button', { name: 'common.save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Write failed');
    expect(model).toHaveValue('local-draft');
    expect(timeout).toHaveValue(120);
    expect(screen.queryByText('settings.codeAgent.saved')).not.toBeInTheDocument();
    const canonical = { ...settings, settings: { ...settings.settings, claude_code: { ...settings.settings.claude_code, default_model: 'canonical' } } };
    vi.mocked(codeAgentApi.patchSettings).mockResolvedValueOnce(canonical);
    await user.click(screen.getByRole('button', { name: 'common.save' }));
    await waitFor(() => expect(model).toHaveValue('canonical'));
    expect(timeout).toHaveValue(600);
    expect(screen.getByRole('button', { name: 'common.save' })).toBeDisabled();
    expect(codeAgentApi.patchSettings).toHaveBeenLastCalledWith('user', expect.objectContaining({ constraints: expect.objectContaining({ default_timeout_s: 120 }) }), null, settings.revision);
  });

  it('keeps detected paths as hints, allows clearing overrides and guards duplicate saves', async () => {
    vi.mocked(codeAgentApi.probe).mockResolvedValue({ results: { ...probe.results, codex: { ...probe.results.codex, binary_path: '/detected/tool' } } });
    let resolve!: (response: SettingsResponse) => void;
    vi.mocked(codeAgentApi.patchSettings).mockReturnValue(new Promise((done) => { resolve = done; }));
    const user = userEvent.setup();
    render(<CodeAgentSection />);
    const inputs = await screen.findAllByLabelText('settings.codeAgent.binaryPathOverride');
    expect(inputs[1]).toHaveValue('');
    expect(inputs[1]).toHaveAttribute('placeholder', '/detected/tool');
    await user.type(inputs[1], '/custom/tool');
    const button = screen.getByRole('button', { name: 'common.save' });
    await user.dblClick(button);
    expect(codeAgentApi.patchSettings).toHaveBeenCalledTimes(1);
    expect(inputs[1]).toBeDisabled();
    await act(async () => { resolve(settings); });
    expect(inputs[1]).toHaveValue('');
  });
});
