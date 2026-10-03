import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { ASRProviderFields } from '@/components/config-forms/ASRProviderFields';
import type { LLMProviderASRConfig } from '@/api/modules/config';
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

it('keeps recognition credentials optional and owned by the provider draft', () => {
  function Form() {
    const [value, setValue] = useState<LLMProviderASRConfig>({ enabled: false, model: null, api_key: '', base_url: '', timeout: 90 });
    return <><ASRProviderFields value={value} onChange={setValue} /><output data-testid="draft">{JSON.stringify(value)}</output></>;
  }
  render(<Form />);
  expect(screen.queryByRole('textbox', { name: 'asr.model' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('switch', { name: 'asr.providerEnabled' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'asr.model' }), { target: { value: 'transcribe-model' } });
  expect(JSON.parse(screen.getByTestId('draft').textContent ?? '{}')).toMatchObject({ enabled: true, model: 'transcribe-model', api_key: '', base_url: '', timeout: 90 });
  fireEvent.click(screen.getByText('asr.connectionOverrides'));
  fireEvent.change(screen.getByLabelText('asr.apiKey'), { target: { value: 'test-only-key' } });
  expect(JSON.parse(screen.getByTestId('draft').textContent ?? '{}')).toMatchObject({ api_key: 'test-only-key', model: 'transcribe-model' });
  fireEvent.click(screen.getByRole('switch', { name: 'asr.providerEnabled' }));
  expect(JSON.parse(screen.getByTestId('draft').textContent ?? '{}')).toMatchObject({ enabled: false, model: 'transcribe-model' });
});
