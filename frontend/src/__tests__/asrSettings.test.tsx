import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { SettingsAsrSection } from '@/components/settings/SettingsAsrSection';
import { DEFAULT_SYSTEM_CONFIG, type SystemConfig } from '@/api/modules/config';
import { asrApi, type ASRModel } from '@/api/modules/asr';

vi.mock('@/api/modules/asr', async importOriginal => ({ ...await importOriginal<typeof import('@/api/modules/asr')>(), asrApi: { models: vi.fn(), modelAction: vi.fn() } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const first: ASRModel = { id: 'paraformer-zh-en-int8', label: 'Paraformer int8', size_bytes: 227405559, state: 'ready', progress: 100, license: 'Apache-2.0', license_url: 'https://example.com/license', source_url: 'https://example.com/source', recommended: false, error: null };
const second: ASRModel = { ...first, id: 'paraformer-zh-en-fp32', label: 'Paraformer float32', size_bytes: 822716780 };
function Settings() {
  const [config, setConfig] = useState(() => {
    const value = structuredClone(DEFAULT_SYSTEM_CONFIG);
    value.speech.asr.enabled = true;
    return value;
  });
  const patch = (update: (draft: SystemConfig) => void) => setConfig(current => { const next = structuredClone(current); update(next); return next; });
  return <><SettingsAsrSection draftConfig={config} patchDraftConfig={patch} /><output data-testid="selection">{config.speech.asr.local_model_id}</output></>;
}
beforeEach(() => { vi.mocked(asrApi.models).mockReset().mockResolvedValue([first, second]); vi.mocked(asrApi.modelAction).mockReset(); });

it('selects downloaded models and prevents deleting the selected enabled model', async () => {
  render(<Settings />);
  const select = await screen.findByRole('combobox', { name: 'asr.selectedModel' });
  await screen.findByRole('group', { name: first.label });
  expect(within(screen.getByRole('group', { name: first.label })).getByRole('button', { name: 'asr.delete' })).toBeDisabled();
  fireEvent.change(select, { target: { value: second.id } });
  expect(screen.getByTestId('selection')).toHaveTextContent(second.id);
  expect(within(screen.getByRole('group', { name: second.label })).getByRole('button', { name: 'asr.delete' })).toBeDisabled();
  expect(within(screen.getByRole('group', { name: first.label })).getByRole('button', { name: 'asr.delete' })).toBeEnabled();
});

it('keeps both model rows after deleting one and prevents selecting missing weights', async () => {
  vi.mocked(asrApi.modelAction).mockResolvedValue({ ...second, state: 'missing', progress: 0 });
  render(<Settings />);
  fireEvent.click(within(await screen.findByRole('group', { name: second.label })).getByRole('button', { name: 'asr.delete' }));
  await waitFor(() => expect(screen.getByRole('option', { name: second.label })).toBeDisabled());
  expect(screen.getByRole('group', { name: first.label })).toBeInTheDocument();
  expect(screen.getByRole('group', { name: second.label })).toBeInTheDocument();
  expect(asrApi.modelAction).toHaveBeenCalledWith(second.id, 'delete');
  fireEvent.change(screen.getByRole('combobox', { name: 'asr.selectedModel' }), { target: { value: second.id } });
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
