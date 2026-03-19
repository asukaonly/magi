import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import PersonalityModern from '@/pages/PersonalityModern';
import { usePersonality } from '@/hooks';
import { personalitiesApi } from '@/api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/api', () => ({
  personalitiesApi: {
    uploadAvatar: vi.fn(),
    getAvatarUrl: vi.fn((avatar?: string) => avatar || ''),
  },
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

  it('keeps the create card selected and only shows AI generation in new mode', () => {
    vi.mocked(usePersonality).mockReturnValue(
      buildHookState({
        isNewMode: true,
        selectedName: '',
        selectedInfo: undefined,
        config: {
          persona_entity: {
            basic_profile: {
              name: '',
              age: '',
              gender: '',
              description: '',
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

    expect(screen.getByTestId('personality-create-card')).toBeInTheDocument();
    expect(screen.getByTestId('personality-create-card').firstElementChild).toHaveClass('border-primary');
    expect(screen.getAllByText('personality.generate')).toHaveLength(2);
  });

  it('hides AI generation when editing an existing personality', () => {
    vi.mocked(usePersonality).mockReturnValue(buildHookState() as any);

    render(<PersonalityModern embedded />);

    expect(screen.queryAllByText('personality.generate')).toHaveLength(0);
  });

  it('uploads an avatar and patches the personality profile', async () => {
    const patch = vi.fn();
    vi.mocked(usePersonality).mockReturnValue(buildHookState({ patch }) as any);
    vi.mocked(personalitiesApi.uploadAvatar).mockResolvedValue({
      data: {
        url: '/static/user-avatars/test-avatar.png',
      },
    } as any);

    render(<PersonalityModern embedded />);

    const fileInput = screen.getByTestId('personality-avatar-input');
    const file = new File(['avatar'], 'avatar.png', { type: 'image/png' });

    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => expect(personalitiesApi.uploadAvatar).toHaveBeenCalledWith(file));
    expect(patch).toHaveBeenCalledTimes(1);
    const draft = buildHookState().config;
    const updater = patch.mock.calls[0][0] as (value: typeof draft) => void;
    updater(draft);
    expect(draft.persona_entity.basic_profile.avatar).toBe('/static/user-avatars/test-avatar.png');
  });
});
