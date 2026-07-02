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

  it('renders a specific message when the runtime loop is unresponsive', () => {
    useBackendHealthStore.setState({
      status: 'degraded',
      runtimeStatus: 'unresponsive',
      startupState: 'unresponsive',
      deferredReason: null,
      llmReady: null,
      agentRuntimeReady: null,
      lastCheckedAt: Date.now(),
    });

    render(<BackendHealthBanner />);

    expect(screen.getByText('desktop.health.degradedRuntimeUnresponsive')).toBeInTheDocument();
  });
});
