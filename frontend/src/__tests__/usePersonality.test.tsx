import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { usePersonality } from '@/hooks';
import { personalityApi } from '@/api';

const tMock = (key: string, params?: Record<string, string>) => {
  if (key === 'personality.switchConfirm' && params) {
    return `switch:${params.from}->${params.to}`;
  }
  return key;
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: tMock,
  }),
}));

vi.mock('@/i18n', () => ({
  default: {
    changeLanguage: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock('@/api', async () => {
  const actual = await vi.importActual<typeof import('@/api')>('@/api');
  return {
    ...actual,
    personalityApi: {
      ...actual.personalityApi,
      list: vi.fn(),
      get: vi.fn(),
      getCurrent: vi.fn(),
      setCurrent: vi.fn(),
      compare: vi.fn(),
      update: vi.fn(),
      updateWithAIName: vi.fn(),
      generate: vi.fn(),
      delete: vi.fn(),
    },
  };
});

const buildConfig = (name: string, onSwitchAttempt: string[] = []) => ({
  persona_entity: {
    basic_profile: {
      name,
      age: '',
      gender: '',
      description: '',
      avatar: '',
      occupation: `${name}-occupation`,
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
    on_switch_attempt: onSwitchAttempt,
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
});

const Harness = () => {
  const {
    list,
    selectedName,
    switchPrompt,
    selectPersonality,
    switchPersonality,
    confirmSwitchPersonality,
  } = usePersonality();

  return (
    <div>
      <div data-testid="selected-name">{selectedName}</div>
      {list.map((item) => (
        <button key={item.name} type="button" onClick={() => selectPersonality(item.name)}>
          {item.displayName}
        </button>
      ))}
      <button
        type="button"
        onClick={() => {
          void switchPersonality();
        }}
      >
        personality.switch
      </button>
      {switchPrompt ? (
        <div>
          <div>{switchPrompt.phrase}</div>
          <div>{`switch:${switchPrompt.fromName}->${switchPrompt.toName}`}</div>
          <button
            type="button"
            onClick={() => {
              void confirmSwitchPersonality();
            }}
          >
            personality.confirmSwitch
          </button>
        </div>
      ) : null}
    </div>
  );
};

describe('usePersonality', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(personalityApi.getCurrent).mockResolvedValue({
      success: true,
      message: 'ok',
      data: {
        current: '七号',
      },
    } as any);
    vi.mocked(personalityApi.list).mockResolvedValue({
      success: true,
      message: 'ok',
      data: {
        personalities: ['七号', '惣流·明日香·兰格雷'],
      },
    } as any);
    vi.mocked(personalityApi.get).mockImplementation(async (name: string) => ({
      success: true,
      message: 'ok',
      data:
        name === '七号'
          ? buildConfig('七号', ['别急着走，再给我一次机会。'])
          : buildConfig('惣流·明日香·兰格雷'),
    }) as any);
    vi.mocked(personalityApi.setCurrent).mockResolvedValue({
      success: true,
      message: 'ok',
      data: {
        current: '惣流·明日香·兰格雷',
      },
    } as any);
  });

  it('opens a retention prompt and switches without calling compare', async () => {
    const user = userEvent.setup();

    render(<Harness />);

    await user.click(await screen.findByRole('button', { name: '惣流·明日香·兰格雷' }));
    await user.click(screen.getByRole('button', { name: 'personality.switch' }));

    expect(personalityApi.compare).not.toHaveBeenCalled();
    expect(await screen.findByText('别急着走，再给我一次机会。')).toBeInTheDocument();
    expect(screen.getByText('switch:七号->惣流·明日香·兰格雷')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'personality.confirmSwitch' }));

    await waitFor(() =>
      expect(personalityApi.setCurrent).toHaveBeenCalledWith('惣流·明日香·兰格雷')
    );
  });
});
