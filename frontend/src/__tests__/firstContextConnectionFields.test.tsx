import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FirstContextConnectionFields } from '@/components/plugins/FirstContextConnectionFields';
import type { ActivationFlowSpec, ExtensionFieldSpec } from '@/api/modules/plugins';
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const field = (key: string, overrides: Partial<ExtensionFieldSpec> = {}): ExtensionFieldSpec => ({
  key, type: 'input', label: key, description: '', section: 'general', surface: 'timeline', order: 0, required: false,
  options: [], ...overrides,
});
const mode = field('sources.s.sync_mode', { type: 'select', default: 'interval', required: true,
  options: [{ label: 'Manual', value: 'manual' }, { label: 'Scheduled', value: 'interval' }] });
const interval = field('sources.s.sync_interval_minutes', { type: 'number', default: 30 });
const flow = { title: 'Connect', description: '', confirm_label: 'Connect', cancel_label: 'Cancel', fields: [mode, interval], enabled_key: 'sources.s.enabled', configured_key: 'sources.s.configured', authorize_on_confirm: false } satisfies ActivationFlowSpec;

describe('FirstContextConnectionFields', () => {
  it('exposes auto sync directly while keeping interval settings collapsed', () => {
    const onChange = vi.fn();
    const { rerender } = render(<FirstContextConnectionFields flow={flow} values={{ [mode.key]: 'interval', [interval.key]: 30 }} onChange={onChange} />);
    expect(screen.getByRole('switch', { name: 'pluginInstallPanel.autoSync' })).toBeChecked();
    expect(screen.getByText('pluginInstallPanel.syncSettings').closest('details')).not.toHaveAttribute('open');
    expect(screen.queryByText('settings.pluginSections.general')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('switch'));
    expect(onChange).toHaveBeenCalledWith(mode.key, 'manual');
    rerender(<FirstContextConnectionFields flow={flow} values={{ [mode.key]: 'manual' }} onChange={onChange} />);
    expect(screen.getByText('pluginInstallPanel.autoSyncOff')).toBeInTheDocument();
    expect(screen.queryByText('pluginInstallPanel.syncSettings')).not.toBeInTheDocument();
  });

  it('keeps required paths and non-binary scheduling modes in the regular form', () => {
    const path = field('directory', { required: true, label: 'Folder' });
    const custom = { ...mode, label: 'Sync mode', options: [...mode.options, { label: 'Realtime', value: 'realtime' }] };
    render(<FirstContextConnectionFields flow={{ ...flow, fields: [path, custom] }} values={{ [mode.key]: 'realtime' }} onChange={vi.fn()} />);
    expect(screen.getByLabelText(/Folder/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sync mode' })).toHaveTextContent('Realtime');
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });
});
