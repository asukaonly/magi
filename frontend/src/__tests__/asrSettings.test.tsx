import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { SettingsAsrSection } from '@/components/settings/SettingsAsrSection';
import { DEFAULT_SYSTEM_CONFIG, type SystemConfig } from '@/api/modules/config';
import { asrApi, type ASRModel } from '@/api/modules/asr';

const runtime = vi.hoisted(() => ({ mode: 'local' }));
vi.mock('@/runtime/config', async original => ({ ...await original<typeof import('@/runtime/config')>(), getRuntimeConfig: () => ({ mode: runtime.mode }) }));
vi.mock('@/api/modules/asr', async original => ({ ...await original<typeof import('@/api/modules/asr')>(), asrApi: { models: vi.fn(), modelAction: vi.fn() } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const first: ASRModel = { family: 'paraformer', id: 'paraformer-zh-en-int8', label: 'Paraformer int8', size_bytes: 227405559, state: 'ready', progress: 100, license: 'Apache-2.0', license_url: 'https://example.com/license', source_url: 'https://example.com/source', recommended: false, error: null };
const variant: ASRModel = { ...first, id: 'paraformer-zh-en-fp32', label: 'Paraformer float32', size_bytes: 822716780 };
const second: ASRModel = { ...first, family: 'sense_voice', id: 'sensevoice-zh-en-ja-ko-yue', label: 'SenseVoice', size_bytes: 239549735 };
const familyName = (model: ASRModel) => `asr.families.${model.family}.name`;
const row = (model: ASRModel) => within(screen.getByRole('group', { name: familyName(model) }));
function Settings({ selected = first.id }: { selected?: string }) {
  const [config, setConfig] = useState(() => {
    const value = structuredClone(DEFAULT_SYSTEM_CONFIG);
    value.speech.asr.enabled = true;
    value.speech.asr.local_model_id = selected;
    return value;
  });
  const patch = (update: (draft: SystemConfig) => void) => setConfig(current => { const next = structuredClone(current); update(next); return next; });
  return <><SettingsAsrSection draftConfig={config} patchDraftConfig={patch} onConfigureProviders={vi.fn()} /><output data-testid="selection">{config.speech.asr.local_model_id}</output></>;
}
beforeEach(() => { runtime.mode = 'local'; vi.mocked(asrApi.models).mockReset().mockResolvedValue([first, variant, second]); vi.mocked(asrApi.modelAction).mockReset(); });

it('offers one choice per model family while preserving an installed precision selection', async () => {
  render(<Settings selected={variant.id} />);
  const user = userEvent.setup();
  await screen.findByRole('radio', { name: familyName(first) });
  expect(screen.getAllByRole('radio')).toHaveLength(2);
  expect(row(first).getByRole('radio')).toBeChecked();
  expect(screen.getByTestId('selection')).toHaveTextContent(variant.id);
  await user.click(row(second).getByRole('radio'));
  expect(screen.getByTestId('selection')).toHaveTextContent(second.id);
  expect(row(second).getByRole('radio')).toBeChecked();
  expect(screen.queryByText(first.label)).not.toBeInTheDocument();
  expect(screen.queryByText(variant.label)).not.toBeInTheDocument();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});

it('selects a new family only after download finishes', async () => {
  vi.mocked(asrApi.models).mockResolvedValue([first, variant, { ...second, state: 'missing' }]);
  vi.mocked(asrApi.modelAction).mockResolvedValue(second);
  render(<Settings />);
  await screen.findByRole('radio', { name: familyName(second) });
  expect(row(second).getByRole('radio')).toBeDisabled();
  fireEvent.click(row(second).getByRole('button', { name: 'asr.download' }));
  await waitFor(() => expect(row(second).getByRole('radio')).toBeEnabled());
  expect(asrApi.modelAction).toHaveBeenCalledWith(second.id, 'download');
  expect(screen.getByTestId('selection')).toHaveTextContent(first.id);
  fireEvent.click(row(second).getByRole('radio'));
  expect(screen.getByTestId('selection')).toHaveTextContent(second.id);
});

it('shows deletion guidance only after an in-use model deletion is rejected', async () => {
  vi.mocked(asrApi.modelAction).mockRejectedValue({ code: 'model_in_use' });
  render(<Settings />);
  await screen.findByRole('radio', { name: familyName(first) });
  expect(screen.queryByText('asr.errors.model_in_use')).not.toBeInTheDocument();
  fireEvent.click(row(first).getByRole('button', { name: 'asr.delete' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('asr.errors.model_in_use');
  expect(asrApi.modelAction).toHaveBeenCalledWith(first.id, 'delete');
  expect(row(first).getByRole('radio')).toBeChecked();
});

it('keeps both model families after deleting one and disables missing weights', async () => {
  vi.mocked(asrApi.modelAction).mockResolvedValue({ ...second, state: 'missing', progress: 0 });
  render(<Settings />);
  await screen.findByRole('radio', { name: familyName(second) });
  fireEvent.click(row(second).getByRole('button', { name: 'asr.delete' }));
  await waitFor(() => expect(row(second).getByRole('status')).toHaveTextContent('asr.modelStates.missing'));
  expect(row(second).getByRole('radio')).toBeDisabled();
  expect(screen.getAllByRole('radio')).toHaveLength(2);
  expect(asrApi.modelAction).toHaveBeenCalledWith(second.id, 'delete');
});

it('does not let an older polling response erase a completed model action', async () => {
  let finishPoll: ((models: ASRModel[]) => void) | undefined;
  vi.mocked(asrApi.models).mockResolvedValueOnce([first, { ...second, state: 'downloading' }]).mockImplementationOnce(() => new Promise(resolve => { finishPoll = resolve; }));
  vi.mocked(asrApi.modelAction).mockResolvedValue({ ...second, state: 'cancelled' });
  render(<Settings />);
  await waitFor(() => expect(asrApi.models).toHaveBeenCalledTimes(2));
  fireEvent.click(row(second).getByRole('button', { name: 'asr.cancel' }));
  vi.mocked(asrApi.models).mockResolvedValue([first, { ...second, state: 'cancelled' }]);
  await waitFor(() => expect(row(second).getByRole('status')).toHaveTextContent('asr.modelStates.cancelled'));
  await act(async () => { finishPoll?.([first, { ...second, state: 'downloading' }]); });
  expect(row(second).getByRole('status')).toHaveTextContent('asr.modelStates.cancelled');
});

it('names the server execution location without claiming local processing', async () => {
  runtime.mode = 'remote';
  render(<Settings />);
  expect(await screen.findByRole('button', { name: 'asr.mode' })).toHaveTextContent('asr.serverModel');
});

it('offers connection setup only when online recognition has no eligible provider', async () => {
  const config = structuredClone(DEFAULT_SYSTEM_CONFIG);
  config.speech.asr.mode = 'remote';
  config.llm.providers = {};
  const configure = vi.fn();
  const view = render(<SettingsAsrSection draftConfig={config} patchDraftConfig={vi.fn()} onConfigureProviders={configure} />);
  fireEvent.click(await screen.findByRole('button', { name: 'asr.addProvider' }));
  expect(configure).toHaveBeenCalledOnce();
  const { cloneProvider } = await import('@/components/config-forms/llm-form-state');
  const provider = cloneProvider();
  provider.enabled = true; provider.services.asr.enabled = true;
  config.llm.providers = { example: provider };
  view.rerender(<SettingsAsrSection draftConfig={config} patchDraftConfig={vi.fn()} onConfigureProviders={configure} />);
  expect(screen.queryByRole('button', { name: 'asr.addProvider' })).not.toBeInTheDocument();
});
