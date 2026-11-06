import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import BackendHealthBanner from '@/components/layout/BackendHealthBanner';
import { useBackendHealthStore } from '@/stores/backend-health';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

describe('BackendHealthBanner', () => {
  beforeEach(() => {
    useBackendHealthStore.setState({
      status: 'healthy',
      runtimeStatus: null,
      startupState: null,
      deferredReason: null,
      llmReady: null,
      agentRuntimeReady: null,
      lastCheckedAt: null,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders a specific message for deferred model selection startup', () => {
    useBackendHealthStore.setState({
      status: 'degraded',
      runtimeStatus: 'deferred',
      startupState: 'deferred',
      deferredReason: 'llm_selection_pending',
      llmReady: false,
      agentRuntimeReady: false,
      lastCheckedAt: Date.now(),
    });

    render(<BackendHealthBanner />);

    expect(screen.getByText('desktop.health.degradedDeferredSelectionPending')).toBeInTheDocument();
  });

  it('keeps invalid model configuration visible until readiness recovers', () => {
    useBackendHealthStore.getState().setHealth('degraded', {
      startupState: 'deferred', deferredReason: 'llm_configuration_invalid',
    });
    const { rerender } = render(<BackendHealthBanner />);
    expect(screen.getByRole('status')).toHaveTextContent('desktop.health.degradedDeferredInvalid');
    useBackendHealthStore.getState().setHealth('healthy');
    rerender(<BackendHealthBanner />);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it.each(['healthy', 'offline', 'exited'] as const)('does not show a global warning for %s', (status) => {
    useBackendHealthStore.getState().setHealth(status);
    const { container } = render(<BackendHealthBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    'starting', 'stale', 'unresponsive', 'probe_timeout', 'disconnected',
    'recovering', 'probe_busy', 'probe_failed', 'deferred',
  ])('keeps %s recovery quiet without hiding explicit configuration errors', (runtimeStatus) => {
    useBackendHealthStore.getState().setHealth('degraded', {
      runtimeStatus, startupState: runtimeStatus, llmReady: false, agentRuntimeReady: false,
    });
    const { container } = render(<BackendHealthBanner />);
    expect(container).toBeEmptyDOMElement();
  });
});
