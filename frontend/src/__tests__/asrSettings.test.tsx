import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { SettingsAsrSection } from '@/components/settings/SettingsAsrSection';
import { DEFAULT_SYSTEM_CONFIG, type SystemConfig } from '@/api/modules/config';
import { asrApi, type ASRModel } from '@/api/modules/asr';

const runtime = vi.hoisted(() => ({ mode: 'local' }));
vi.mock('@/runtime/config', async original => ({ ...await original<typeof import('@/runtime/config')>(), getRuntimeConfig: () => ({ mode: runtime.mode }) }));
vi.mock('@/api/modules/asr', async importOriginal => ({ ...await importOriginal<typeof import('@/api/modules/asr')>(), asrApi: { models: vi.fn(), modelAction: vi.fn() } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? key }) }));
const first: ASRModel = { id: 'paraformer-zh-en-int8', label: 'Paraformer int8', size_bytes: 227405559, state: 'ready', progress: 100, license: 'Apache-2.0', license_url: 'https://example.com/license', source_url: 'https://example.com/source', recommended: false, error: null };
const second: ASRModel = { ...first, id: 'paraformer-zh-en-fp32', label: 'Paraformer float32', size_bytes: 822716780 };
function Settings() {
  const [config, setConfig] = useState(() => {
    const value = structuredClone(DEFAULT_SYSTEM_CONFIG);
    value.speech.asr.enabled = true;
    return value;
  });
  const patch = (update: (draft: SystemConfig) => void) => setConfig(current => { const next = structuredClone(current); update(next); return next; });
  return <><SettingsAsrSection draftConfig={config} patchDraftConfig={patch} onConfigureProviders={vi.fn()} onConfigureVoice={vi.fn()} /><output data-testid="selection">{config.speech.asr.local_model_id}</output></>;
}
beforeEach(() => { runtime.mode = 'local'; vi.mocked(asrApi.models).mockReset().mockResolvedValue([first, second]); vi.mocked(asrApi.modelAction).mockReset(); });

it('selects downloaded models and prevents deleting the selected enabled model', async () => {
  render(<Settings />);
  const user = userEvent.setup();
  const select = await screen.findByRole('button', { name: 'asr.selectedModel' });
  await screen.findByRole('group', { name: first.label });
  expect(within(screen.getByRole('group', { name: first.label })).getByRole('button', { name: 'asr.delete' })).toBeDisabled();
  await user.click(select);
  await user.click(screen.getByRole('button', { name: second.label }));
  expect(screen.getByTestId('selection')).toHaveTextContent(second.id);
  expect(within(screen.getByRole('group', { name: second.label })).getByRole('button', { name: 'asr.delete' })).toBeDisabled();
  expect(within(screen.getByRole('group', { name: first.label })).getByRole('button', { name: 'asr.delete' })).toBeEnabled();
});

it('keeps both model rows after deleting one and prevents selecting missing weights', async () => {
  vi.mocked(asrApi.modelAction).mockResolvedValue({ ...second, state: 'missing', progress: 0 });
  render(<Settings />);
  fireEvent.click(within(await screen.findByRole('group', { name: second.label })).getByRole('button', { name: 'asr.delete' }));
  await waitFor(() => expect(within(screen.getByRole('group', { name: second.label })).getByRole('status')).toHaveTextContent('asr.modelStates.missing'));
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: 'asr.selectedModel' }));
  expect(screen.getByRole('button', { name: second.label })).toBeDisabled();
  expect(screen.getByRole('group', { name: first.label })).toBeInTheDocument();
  expect(screen.getByRole('group', { name: second.label })).toBeInTheDocument();
  expect(asrApi.modelAction).toHaveBeenCalledWith(second.id, 'delete');
  await user.click(screen.getByRole('button', { name: second.label }));
  expect(screen.getByTestId('selection')).toHaveTextContent(first.id);
});

it('does not let an older polling response erase a completed model action', async () => {
  let finishPoll: ((models: ASRModel[]) => void) | undefined;
  vi.mocked(asrApi.models).mockResolvedValueOnce([first, { ...second, state: 'downloading' }]).mockImplementationOnce(() => new Promise(resolve => { finishPoll = resolve; }));
  vi.mocked(asrApi.modelAction).mockResolvedValue({ ...second, state: 'cancelled' });
  render(<Settings />);
  await waitFor(() => expect(asrApi.models).toHaveBeenCalledTimes(2));
  fireEvent.click(within(screen.getByRole('group', { name: second.label })).getByRole('button', { name: 'asr.cancel' }));
  vi.mocked(asrApi.models).mockResolvedValue([first, { ...second, state: 'cancelled' }]);
  await waitFor(() => expect(within(screen.getByRole('group', { name: second.label })).getByRole('status')).toHaveTextContent('asr.modelStates.cancelled'));
  await act(async () => { finishPoll?.([first, { ...second, state: 'downloading' }]); });
  expect(within(screen.getByRole('group', { name: second.label })).getByRole('status')).toHaveTextContent('asr.modelStates.cancelled');
});


it('describes recognition on a connected server without claiming audio stays on this computer', async () => {
  runtime.mode = 'remote';
  render(<Settings />);
  expect(await screen.findByRole('button', { name: 'asr.mode' })).toHaveTextContent('asr.serverModel');
  expect(screen.getByText('asr.remoteCenterLocation')).toBeInTheDocument();
  expect(screen.queryByText('asr.localLocation')).not.toBeInTheDocument();
});

it('routes online recognition connection setup to the shared provider editor', async () => {
  const config = structuredClone(DEFAULT_SYSTEM_CONFIG);
  config.speech.asr.enabled = true;
  config.speech.asr.mode = 'remote';
  const configure = vi.fn();
  render(<SettingsAsrSection draftConfig={config} patchDraftConfig={vi.fn()} onConfigureProviders={configure} onConfigureVoice={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'asr.configureProvider' }));
  expect(configure).toHaveBeenCalledOnce();
  expect(screen.queryByLabelText('asr.endpoint')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('asr.apiKey')).not.toBeInTheDocument();
});
