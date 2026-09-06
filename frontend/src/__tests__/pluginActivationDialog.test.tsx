import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { PluginActivationDialog } from '@/components/plugins/PluginActivationDialog';
import type { ActivationFlowSpec, ExtensionFieldSpec } from '@/api/modules/plugins';

const { pickDirectoryMock, pickFileMock } = vi.hoisted(() => ({
  pickDirectoryMock: vi.fn(),
  pickFileMock: vi.fn(),
}));

vi.mock('@/runtime/desktop', () => ({
  pickDirectory: pickDirectoryMock,
  pickFile: pickFileMock,
}));

vi.mock('react-i18next', async () => {
  const actual: any = await vi.importActual('react-i18next');
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string, opts?: any) => {
        if (opts && typeof opts === 'object') {
          return `${key} ${JSON.stringify(opts)}`;
        }
        return key;
      },
    }),
  };
});

const profilePathField: ExtensionFieldSpec = {
  key: 'source_path',
  type: 'input',
  label: 'Profile Path',
  description: '',
  default: '',
  required: true,
  options: [],
  section: 'general',
  surface: 'timeline',
  order: 1,
};

const fakeFlow: ActivationFlowSpec = {
  title: 'Connect Chrome',
  description: 'Authorise Chrome timeline access.',
  confirm_label: 'Connect',
  cancel_label: 'Cancel',
  enabled_key: 'enabled',
  configured_key: 'configured',
  authorize_on_confirm: false,
  fields: [profilePathField],
};

describe('PluginActivationDialog', () => {
  beforeEach(() => {
    pickDirectoryMock.mockReset();
    pickDirectoryMock.mockResolvedValue(undefined);
    pickFileMock.mockReset();
    pickFileMock.mockResolvedValue(undefined);
  });

  it('does not render when open is false', () => {
    render(
      <PluginActivationDialog
        open={false}
        onClose={() => {}}
        flow={fakeFlow}
        initialValues={{}}
        onConfirm={async () => {}}
      />,
    );
    expect(screen.queryByText(/Connect Chrome/)).not.toBeInTheDocument();
  });

  it('renders flow title and each field', () => {
    render(
      <PluginActivationDialog
        open={true}
        onClose={() => {}}
        flow={fakeFlow}
        initialValues={{}}
        onConfirm={async () => {}}
      />,
    );
    expect(screen.getByText(/Connect Chrome/)).toBeInTheDocument();
    expect(screen.getByText(/Profile Path/)).toBeInTheDocument();
  });

  it('disables Confirm until required fields are filled', async () => {
    const user = userEvent.setup();
    render(
      <PluginActivationDialog
        open={true}
        onClose={() => {}}
        flow={fakeFlow}
        initialValues={{}}
        onConfirm={async () => {}}
      />,
    );
    const confirm = screen.getByRole('button', { name: /confirm|connect|启用|确认/i });
    expect(confirm).toBeDisabled();
    const input = screen
      .getAllByRole('textbox')
      .find((el) => el.tagName === 'INPUT') as HTMLInputElement;
    await user.type(input, '/path');
    await waitFor(() => expect(confirm).not.toBeDisabled());
  });

  it('invokes onConfirm with field values when Confirm clicked', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(
      <PluginActivationDialog
        open={true}
        onClose={() => {}}
        flow={fakeFlow}
        initialValues={{}}
        onConfirm={onConfirm}
      />,
    );
    const input = screen
      .getAllByRole('textbox')
      .find((el) => el.tagName === 'INPUT') as HTMLInputElement;
    await user.type(input, '/path');
    await user.click(screen.getByRole('button', { name: /confirm|connect|启用|确认/i }));
    await waitFor(() =>
      expect(onConfirm).toHaveBeenCalledWith({ source_path: '/path' }),
    );
  });

  it('uses a native folder picker for a localized scalar directory field', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    pickDirectoryMock.mockResolvedValue('/Users/example/My Vault');
    const vaultField: ExtensionFieldSpec = {
      ...profilePathField,
      key: 'sources.obsidian_vault.vault_path',
      type: 'path',
      path_kind: 'directory',
      label: 'Obsidian Vault Folder',
      label_translated: 'Obsidian 笔记库文件夹',
      description: 'Choose the root folder of your Obsidian vault.',
      description_translated: '选择包含 .obsidian 文件夹的笔记库根目录。',
    };

    render(
      <PluginActivationDialog
        open={true}
        onClose={() => {}}
        flow={{ ...fakeFlow, fields: [vaultField] }}
        initialValues={{}}
        onConfirm={onConfirm}
      />,
    );

    expect(
      screen.getByText('选择包含 .obsidian 文件夹的笔记库根目录。'),
    ).toBeInTheDocument();
    const picker = screen.getByRole('button', {
      name: 'Obsidian 笔记库文件夹: settings.browseFolder',
    });
    await user.click(picker);

    expect(pickDirectoryMock).toHaveBeenCalledWith(undefined);
    expect(screen.getByText('/Users/example/My Vault')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /confirm|connect|启用|确认/i }));
    await waitFor(() =>
      expect(onConfirm).toHaveBeenCalledWith({
        'sources.obsidian_vault.vault_path': '/Users/example/My Vault',
      }),
    );
  });

  it('calls onClose when the dialog is dismissed without confirming', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <PluginActivationDialog
        open={true}
        onClose={onClose}
        flow={fakeFlow}
        initialValues={{}}
        onConfirm={async () => {}}
      />,
    );
    await user.click(screen.getByRole('button', { name: /cancel|关闭|取消/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('seeds field defaults so a dependent field is visible on open', () => {
    // A select defaulting to "lookback_days" + a number field shown only when
    // the scope equals "lookback_days". Without default-seeding, values starts
    // empty and the dependent field stays hidden.
    const scopeField: ExtensionFieldSpec = {
      key: 'scope', type: 'select', label: 'First Sync Scope', description: '',
      default: 'lookback_days', required: false, section: 'activation', surface: 'timeline', order: 1,
      options: [
        { label: 'Full', value: 'full' },
        { label: 'Recent days', value: 'lookback_days' },
      ],
    };
    const daysField: ExtensionFieldSpec = {
      key: 'days', type: 'number', label: 'Recent Days', description: '',
      default: 7, required: false, options: [], section: 'activation', surface: 'timeline', order: 2,
      depends_on_key: 'scope', depends_on_values: ['lookback_days'],
    };
    const condFlow: ActivationFlowSpec = {
      ...fakeFlow, fields: [scopeField, daysField],
    };
    render(
      <PluginActivationDialog
        open={true}
        onClose={() => {}}
        flow={condFlow}
        initialValues={{}}
        onConfirm={async () => {}}
      />,
    );
    expect(screen.getByText(/Recent Days/)).toBeInTheDocument();
  });
});
