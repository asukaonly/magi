import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { EmptyStateSourceCard } from '../components/empty-state/EmptyStateSourceCard';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe('EmptyStateSourceCard', () => {
  it('renders plugin-owned title and value text', () => {
    render(
      <EmptyStateSourceCard
        pluginId="chrome-history"
        title="Chrome 浏览器历史"
        value="最近浏览内容"
        onConnect={() => {}}
      />,
    );
    expect(
      screen.getByText('Chrome 浏览器历史'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('最近浏览内容'),
    ).toBeInTheDocument();
  });

  it('invokes onConnect with pluginId when Connect button clicked', async () => {
    const onConnect = vi.fn();
    render(
      <EmptyStateSourceCard
        pluginId="chrome-history"
        title="t1"
        value="v1"
        onConnect={onConnect}
      />,
    );
    await userEvent.click(
      screen.getByRole('button', { name: /connect|启用|连接/i }),
    );
    expect(onConnect).toHaveBeenCalledWith('chrome-history');
  });

  it('defaults the connect button label to emptyState.connect', () => {
    render(
      <EmptyStateSourceCard
        pluginId="chrome-history"
        title="t"
        value="v"
        onConnect={() => {}}
      />,
    );
    expect(
      screen.getByTestId('empty-state-connect-chrome-history'),
    ).toHaveTextContent('emptyState.connect');
  });

  it('renders the connectLabelKey label when provided', () => {
    render(
      <EmptyStateSourceCard
        pluginId="chrome-history"
        title="t"
        value="v"
        onConnect={() => {}}
        connectLabelKey="emptyState.installAndConnect"
      />,
    );
    // The mocked `t` echoes the key, so the button text is the key itself.
    expect(
      screen.getByTestId('empty-state-connect-chrome-history'),
    ).toHaveTextContent('emptyState.installAndConnect');
  });

  it('prefixes labels for page-specific copies', () => {
    render(
      <EmptyStateSourceCard
        pluginId="chrome-history"
        title="Chrome"
        value="History"
        onConnect={() => {}}
        i18nNamespace="app"
        i18nKeyPrefix="timeline"
        connectLabelKey="emptyState.installAndConnect"
      />,
    );
    expect(screen.getByText('Chrome')).toBeInTheDocument();
    expect(
      screen.getByTestId('empty-state-connect-chrome-history'),
    ).toHaveTextContent('timeline.emptyState.installAndConnect');
  });

  it('renders disabled state when disabled prop is true', () => {
    render(
      <EmptyStateSourceCard
        pluginId="chrome-history"
        title="t"
        value="v"
        onConnect={() => {}}
        disabled
      />,
    );
    expect(
      screen.getByRole('button', { name: /connect|启用|连接/i }),
    ).toBeDisabled();
  });
});
