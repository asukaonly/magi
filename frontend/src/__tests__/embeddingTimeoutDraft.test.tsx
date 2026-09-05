import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import fixtures from '../../../contracts/api/frontend-config-examples.json';
import { toSystemConfig } from '@/api/config-contract';
import { validateConfigResponse } from '@/api/generated/config-validators';
import { LLMLocalEmbeddingModelPanel } from '@/components/config-forms/LLMLocalEmbeddingModelPanel';
import { isEmbeddingIdleTimeoutValid } from '@/utils/memory-settings-validation';
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const response: unknown = fixtures.config;
if (!validateConfigResponse(response) || !response.data) throw new Error('Invalid fixture');
const initial = toSystemConfig(response.data).memory.embedding;
function Editor() {
  const [config, setConfig] = useState(initial);
  return <LLMLocalEmbeddingModelPanel embeddingConfig={config} onEmbeddingConfigChange={(update) => setConfig((current) => { const next = structuredClone(current); update(next); return next; })} inputClassName="" presetModels={[]} downloadError={null} downloadingModelId={null} downloadProgress={null} onDownloadModel={vi.fn()} onDeleteModel={vi.fn()} onPickDirectory={vi.fn()} onRefreshModels={vi.fn()} />;
}
describe('embedding idle timeout', () => {
  it('keeps an empty draft and explains the error instead of restoring a hidden default', async () => {
    const user = userEvent.setup(); render(<Editor />);
    const input = screen.getByRole('spinbutton');
    await user.clear(input);
    expect(input).toHaveValue(null);
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('alert')).toHaveTextContent('settings.memory.validation.embeddingIdleTimeout');
    await user.type(input, '1.5');
    expect(input).toHaveValue(1.5);
    expect(input).toHaveAttribute('aria-invalid', 'false');
  });
  it('matches the backend whole-seconds constraint', () => {
    for (const value of [Number.NaN, Infinity, 0, 59, 60.5]) expect(isEmbeddingIdleTimeoutValid(value)).toBe(false);
    for (const value of [60, 90, 1800]) expect(isEmbeddingIdleTimeoutValid(value)).toBe(true);
  });
});
