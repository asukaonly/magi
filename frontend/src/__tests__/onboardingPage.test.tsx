import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { configApi } from '@/api/modules/config';
import OnboardingPage from '@/pages/Onboarding';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
  },
}));

vi.mock('@/components/onboarding/OnboardingFlow', () => ({
  default: () => <div>onboarding-flow</div>,
}));

vi.mock('@/api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/config')>('@/api/modules/config');
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      getOnboardingTemplate: vi.fn().mockResolvedValue({
        data: {
          config: actual.DEFAULT_SYSTEM_CONFIG,
        },
      }),
    },
  };
});

describe('OnboardingPage', () => {
  it('loads the onboarding template and renders the onboarding flow', async () => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });

    render(<OnboardingPage />);

    await screen.findByText('onboarding-flow');
    expect(configApi.getOnboardingTemplate).toHaveBeenCalled();
  });
});
