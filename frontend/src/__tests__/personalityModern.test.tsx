import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import PersonalityModern from '@/pages/PersonalityModern';
import { usePersonality } from '@/hooks';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/hooks', () => ({
  usePersonality: vi.fn(),
  CONFIDENCE_OPTIONS: ['Low', 'Medium', 'High'],
  parseLines: (value: string) => value.split('\n').filter(Boolean),
  toLines: (value: string[]) => value.join('\n'),
  getInitials: (value: string) => value.slice(0, 1),
  normalizeTransition: (value: Record<string, string>) => ({
    trigger_type: '',
    trigger_condition: '',
    target_state_name: '',
    behavior_shift: '',
    ...value,
  }),
}));

const buildHookState = (overrides: Partial<Record<string, unknown>> = {}) => ({
  config: {
    persona_entity: {
      basic_profile: {
        name: '七号',
        age: '',
        gender: '',
        description: '赛博乐子人 / 反讽大师',
        avatar: '',
        occupation: '',
        core_background: '',
      },
      psychological_traits: {
        communication_tone: '',
        confidence_level: 'Medium',
        empathy_threshold: '',
        high_frequency_keywords: [],
      },
      social_responses: {
        praise_reaction: '',
        criticism_reaction: '',
        obedience_strategy: '',
      },
      behavioral_strategies: {
        error_handling: '',
        refusal_style: '',
      },
    },
    cached_phrases: {
      on_init: [],
      on_wake: [],
      on_error_generic: [],
      on_success: [],
      on_switch_attempt: [],
    },
    appearance_prompt: '',
    state_transition_protocol: [
      {
        trigger_type: '',
        trigger_condition: '',
        target_state_name: '',
        behavior_shift: '',
      },
    ],
  },
  list: [
    { name: '七号', displayName: '七号', subtitle: '赛博乐子人 / 反讽大师' },
    { name: '明日香', displayName: '明日香', subtitle: '傲娇驾驶员' },
  ],
  currentName: '七号',
  selectedName: '七号',
  isNewMode: false,
  loading: false,
  saving: false,
  generating: false,
  switching: false,
  selectedInfo: { name: '七号', displayName: '七号', subtitle: '赛博乐子人 / 反讽大师' },
  switchPrompt: null,
  prompt: '',
  setPrompt: vi.fn(),
  targetLanguage: 'Auto',
  setTargetLanguage: vi.fn(),
  patch: vi.fn(),
  selectPersonality: vi.fn(),
  startNewPersonality: vi.fn(),
  cancelNewPersonality: vi.fn(),
  save: vi.fn(),
  generate: vi.fn(),
  switchPersonality: vi.fn(),
  confirmSwitchPersonality: vi.fn(),
  cancelSwitchPersonality: vi.fn(),
  deletePersonality: vi.fn(),
  reload: vi.fn(),
  ...overrides,
});

describe('PersonalityModern', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows the current badge beside the active personality name', () => {
    vi.mocked(usePersonality).mockReturnValue(buildHookState() as any);

    render(<PersonalityModern embedded />);

    expect(screen.getByRole('heading', { name: '七号' })).toBeInTheDocument();
    expect(screen.getAllByText('personality.current')).toHaveLength(1);
  });

  it('hides the current badge when viewing a non-active personality', () => {
    vi.mocked(usePersonality).mockReturnValue(
      buildHookState({
        selectedName: '明日香',
        selectedInfo: { name: '明日香', displayName: '明日香', subtitle: '傲娇驾驶员' },
        config: {
          persona_entity: {
            basic_profile: {
              name: '明日香',
              age: '',
              gender: '',
              description: '傲娇驾驶员',
              avatar: '',
              occupation: '',
              core_background: '',
            },
            psychological_traits: {
              communication_tone: '',
              confidence_level: 'Medium',
              empathy_threshold: '',
              high_frequency_keywords: [],
            },
            social_responses: {
              praise_reaction: '',
              criticism_reaction: '',
              obedience_strategy: '',
            },
            behavioral_strategies: {
              error_handling: '',
              refusal_style: '',
            },
          },
          cached_phrases: {
            on_init: [],
            on_wake: [],
            on_error_generic: [],
            on_success: [],
            on_switch_attempt: [],
          },
          appearance_prompt: '',
          state_transition_protocol: [
            {
              trigger_type: '',
              trigger_condition: '',
              target_state_name: '',
              behavior_shift: '',
            },
          ],
        },
      }) as any
    );

    render(<PersonalityModern embedded />);

    expect(screen.getByRole('heading', { name: '明日香' })).toBeInTheDocument();
    expect(screen.queryByText('personality.current')).not.toBeInTheDocument();
  });
});
