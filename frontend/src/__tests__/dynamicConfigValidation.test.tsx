import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ToolConfigSpec } from '@/api/modules/tools';
import type { ExtensionFieldSpec } from '@/api/modules/plugins';
import { readConnectionSetting } from '@/utils/plugin-connection-settings';
import { DynamicConfigField } from '@/components/config-forms/DynamicConfigField';
import { isExtensionFieldVisible, validateDynamicConfigValue } from '@/components/config-forms/dynamic-config-specs';

const { pickDirectory } = vi.hoisted(() => ({ pickDirectory: vi.fn() }));
vi.mock('@/runtime/desktop', () => ({ pickDirectory, pickFile: vi.fn() }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

const spec: ToolConfigSpec = {
  path: 'config', type: 'object', description: 'Configuration', sensitive: false,
  read_only: false, required: false, is_template: false,
};
const field: ExtensionFieldSpec = {
  key: 'folder', type: 'path', path_kind: 'directory', label: 'Folder', description: '',
  required: false, options: [], section: 'general', surface: 'timeline', order: 0,
};

function Editor({ initial = {}, type = 'object' }: { initial?: unknown; type?: ToolConfigSpec['type'] }) {
  const [value, setValue] = useState<unknown>(initial);
  return <DynamicConfigField spec={{ ...spec, type }} value={value} onChange={setValue} />;
}

describe('dynamic configuration values', () => {
  it.each([
    ['integer', 1.5, 'integer'], ['integer', 2, null], ['float', '', 'number'],
    ['float', Infinity, 'number'], ['float', NaN, 'number'], ['float', 1.5, null],
    ['boolean', 'false', 'boolean'], ['boolean', false, null],
    ['array', ['valid', 2], 'stringArray'], ['array', ['valid'], null],
    ['object', '{', 'object'], ['object', [], 'object'], ['object', { ready: true }, null],
    ['string', 42, 'string'],
  ] satisfies [ToolConfigSpec['type'], unknown, string | null][])('checks %s values without coercion', (type, value, issue) => {
    expect(validateDynamicConfigValue({ ...spec, type }, value)).toBe(issue);
  });

  it('checks selection membership and only activates visible required fields', () => {
    expect(validateDynamicConfigValue({ ...field, type: 'select', options: [{ label: 'Daily', value: 'daily' }] }, 'hourly')).toBe('selection');
    expect(isExtensionFieldVisible({ ...field, required: true, depends_on_key: 'mode', depends_on_values: ['custom'] }, { mode: 'auto' })).toBe(false);
    expect(validateDynamicConfigValue({ ...field, required: true }, '  ')).toBe('required');
  });

  it('preserves invalid JSON text until the user finishes the object', () => {
    render(<Editor />);
    const input = screen.getByRole('textbox', { name: 'Configuration' });
    fireEvent.change(input, { target: { value: '{"enabled":' } });
    expect(input).toHaveValue('{"enabled":');
    expect(screen.getByRole('alert')).toHaveTextContent('settings.dynamicValidation.object');
    fireEvent.change(input, { target: { value: '{"enabled":true}' } });
    expect(JSON.parse((input as HTMLTextAreaElement).value)).toEqual({ enabled: true });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('keeps a cleared numeric draft empty instead of converting it to zero', () => {
    render(<Editor initial={42} type="integer" />);
    const input = screen.getByRole('spinbutton', { name: 'Configuration' });
    fireEvent.change(input, { target: { value: '' } });
    expect(input).toHaveValue(null);
    expect(screen.getByRole('alert')).toHaveTextContent('settings.dynamicValidation.number');
  });

  it('shows native picker failure and permits retry', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    pickDirectory.mockRejectedValueOnce(new Error('Picker failed')).mockResolvedValueOnce('/selected');
    render(<DynamicConfigField spec={field} value="" onChange={onChange} />);
    const button = screen.getByRole('button', { name: 'Folder: settings.browseFolder' });
    await user.click(button);
    expect(screen.getByRole('alert')).toHaveTextContent('settings.dynamicValidation.pickerFailed');
    await user.click(button);
    expect(onChange).toHaveBeenCalledWith('/selected');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('reads own nested settings without traversing inherited properties', () => {
    expect(readConnectionSetting({ nested: { enabled: false } }, 'nested.enabled', true)).toBe(false);
    expect(readConnectionSetting({}, 'toString', 'missing')).toBe('missing');
    expect(readConnectionSetting({ nested: null }, 'nested.enabled', false)).toBe(false);
  });
});
