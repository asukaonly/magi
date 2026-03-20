import { MemoryRouter, useLocation } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';

import Header from '@/components/layout/Header';
import { useChatShellStore } from '@/stores';

describe('header navigation', () => {
  const LocationProbe = () => {
    const location = useLocation();
    return <div data-testid="location">{location.pathname}</div>;
  };

  beforeEach(() => {
    useChatShellStore.setState({
      currentSessionId: null,
      activePanel: 'none',
    });
  });

  it('renders a timeline action and navigates to the timeline route', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Header />
        <LocationProbe />
      </MemoryRouter>
    );

    await user.click(screen.getByRole('button', { name: 'shell.timeline' }));

    expect(screen.getByTestId('location')).toHaveTextContent('/timeline');
    expect(useChatShellStore.getState().activePanel).toBe('timeline');
  });

  it('does not render a standalone personality shortcut', () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Header />
      </MemoryRouter>
    );

    expect(screen.queryByRole('button', { name: 'shell.personality' })).not.toBeInTheDocument();
  });
});
