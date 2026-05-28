import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { EmptyStateSensorCard } from '../components/empty-state/EmptyStateSensorCard';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe('EmptyStateSensorCard', () => {
  it('renders title and value labels from i18n keys', () => {
    render(
      <EmptyStateSensorCard
        pluginId="chrome-history"
        titleKey="emptyState.plugins.chromeHistory.title"
        valueKey="emptyState.plugins.chromeHistory.value"
        onConnect={() => {}}
      />,
    );
    expect(
      screen.getByText('emptyState.plugins.chromeHistory.title'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('emptyState.plugins.chromeHistory.value'),
    ).toBeInTheDocument();
  });

  it('invokes onConnect with pluginId when Connect button clicked', async () => {
    const onConnect = vi.fn();
    render(
      <EmptyStateSensorCard
        pluginId="chrome-history"
        titleKey="t1"
        valueKey="v1"
        onConnect={onConnect}
      />,
    );
    await userEvent.click(
      screen.getByRole('button', { name: /connect|启用|连接/i }),
    );
    expect(onConnect).toHaveBeenCalledWith('chrome-history');
  });

  it('renders disabled state when disabled prop is true', () => {
    render(
      <EmptyStateSensorCard
        pluginId="chrome-history"
        titleKey="t"
        valueKey="v"
        onConnect={() => {}}
        disabled
      />,
    );
    expect(
      screen.getByRole('button', { name: /connect|启用|连接/i }),
    ).toBeDisabled();
  });
});
