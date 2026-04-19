import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { usePersonality } from '@/hooks';

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

const mockPersonasApi = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  getActive: vi.fn(),
  setActive: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
}));

vi.mock('@/api/modules/personas', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/personas')>('@/api/modules/personas');
  return {
    ...actual,
    personasApi: mockPersonasApi,
  };
});

const buildConfig = (name: string) => ({
  persona_entity: {
    basic_profile: {
      name,
      age: '',
      gender: '',
      description: '',
      avatar: '',
      occupation: `${name}-occupation`,
    },
    core_identity: {
      inner_narrative: '',
      language_fingerprint: '',
      attention_bias: '',
    },
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
    selectedId,
    switchPrompt,
    selectPersonality,
    switchPersonality,
    confirmSwitchPersonality,
  } = usePersonality();

  return (
    <div>
      <div data-testid="selected-id">{selectedId}</div>
      {list.map((item) => (
        <button key={item.id} type="button" onClick={() => selectPersonality(item.id)}>
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
    mockPersonasApi.getActive.mockResolvedValue({
      success: true,
      persona_id: 'uuid-seven',
    });
    mockPersonasApi.list.mockResolvedValue({
      data: [
        { persona_id: 'uuid-seven', name: '七号', slug: 'seven', locale: 'zh', avatar_path: '', group_name: 'general', sort_order: 0, is_builtin: true, description: '' },
        { persona_id: 'uuid-asuka', name: '惣流·明日香·兰格雷', slug: 'asuka', locale: 'zh', avatar_path: '', group_name: 'general', sort_order: 1, is_builtin: true, description: '' },
      ],
    });
    mockPersonasApi.get.mockImplementation(async (id: string) => ({
      data: {
        persona_id: id,
        name: id === 'uuid-seven' ? '七号' : '惣流·明日香·兰格雷',
        slug: id === 'uuid-seven' ? 'seven' : 'asuka',
        locale: 'zh',
        config: id === 'uuid-seven'
          ? buildConfig('七号')
          : buildConfig('惣流·明日香·兰格雷'),
        avatar_path: '',
        group_name: 'general',
        sort_order: 0,
        is_builtin: true,
        seed_slug: null,
        created_at: 0,
        updated_at: 0,
      },
    }));
    mockPersonasApi.setActive.mockResolvedValue({
      success: true,
      persona_id: 'uuid-asuka',
    });
  });

  it('opens a retention prompt and switches via persona registry', async () => {
    const user = userEvent.setup();

    render(<Harness />);

    await user.click(await screen.findByRole('button', { name: '惣流·明日香·兰格雷' }));
    await user.click(screen.getByRole('button', { name: 'personality.switch' }));

    expect(await screen.findByText('别急着走，再给我一次机会。')).toBeInTheDocument();
    expect(screen.getByText('switch:七号->惣流·明日香·兰格雷')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'personality.confirmSwitch' }));

    await waitFor(() =>
      expect(mockPersonasApi.setActive).toHaveBeenCalledWith('uuid-asuka')
    );
  });
});
