import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { PluginActivationDialog } from '@/components/plugins/PluginActivationDialog';
import type { ActivationFlowSpec, ExtensionFieldSpec } from '@/api/modules/plugins';

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
});
