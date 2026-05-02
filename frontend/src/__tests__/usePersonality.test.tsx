import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { usePersonality } from '@/hooks';
import { toast } from 'sonner';

const tMock = (key: string, params?: Record<string, string>) => {
  if (key === 'personality.switchConfirm' && params) {
    return `switch:${params.from}->${params.to}`;
  }
  if (key === 'personality.switchPromptFallback') {
    return '先别急着走，再给我一次机会。';
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
  generate: vi.fn(),
  generateWithProgress: vi.fn(),
}));

vi.mock('@/api/modules/personas', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/personas')>('@/api/modules/personas');
  return {
    ...actual,
    personasApi: mockPersonasApi,
  };
});

const buildConfig = (name: string) => ({
  name,
  avatar: '',
  description: '',
  appearance_prompt: '',
  identity_core: { identity_statement: '', values_loved: [], values_rejected: [], attention_biases: [] },
  idiolect: { sentence_style: '', vocab_available: [], vocab_avoided: [], structural_quirks: [] },
  registers: {},
  quiet_hours: [],
  signature_triggers: [],
  persona_layers: [],
  dynamic_state_rules: {},
  milestone_conditions: {},
  interim_lines: {},
  bootstrap: null,
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

const GenerateHarness = () => {
  const { config, prompt, setPrompt, generate } = usePersonality();

  return (
    <div>
      <div data-testid="config-name">{config.name}</div>
      <input aria-label="generation prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} />
      <button type="button" onClick={() => { void generate(); }}>
        generate
      </button>
    </div>
  );
};

const SaveHarness = () => {
  const { startNewPersonality, save } = usePersonality();

  return (
    <div>
      <button type="button" onClick={startNewPersonality}>new</button>
      <button type="button" onClick={() => { void save(); }}>save</button>
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
    mockPersonasApi.generateWithProgress.mockResolvedValue({
      data: {
        name: 'Generated',
        identity_core: { identity_statement: 'Generated core.' },
      },
    });
  });

  it('opens a retention prompt and switches via persona registry', async () => {
    const user = userEvent.setup();

    render(<Harness />);

    await user.click(await screen.findByRole('button', { name: '惣流·明日香·兰格雷' }));
    await user.click(screen.getByRole('button', { name: 'personality.switch' }));

    expect(await screen.findByText('先别急着走，再给我一次机会。')).toBeInTheDocument();
    expect(screen.getByText('switch:七号->惣流·明日香·兰格雷')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'personality.confirmSwitch' }));

    await waitFor(() =>
      expect(mockPersonasApi.setActive).toHaveBeenCalledWith('uuid-asuka')
    );
  });

  it('passes the current draft config into AI generation', async () => {
    const user = userEvent.setup();

    render(<GenerateHarness />);

    await waitFor(() => expect(screen.getByTestId('config-name')).toHaveTextContent('七号'));
    await user.type(screen.getByLabelText('generation prompt'), 'make it sharper');
    await user.click(screen.getByRole('button', { name: 'generate' }));

    await waitFor(() => expect(mockPersonasApi.generateWithProgress).toHaveBeenCalled());
    expect(mockPersonasApi.generateWithProgress.mock.calls[0][0]).toMatchObject({
      description: 'make it sharper',
      current_config: { name: '七号' },
    });
  });

  it('blocks saving a persona that is missing minimum runtime fields', async () => {
    const user = userEvent.setup();

    render(<SaveHarness />);

    await user.click(screen.getByRole('button', { name: 'new' }));
    await user.click(screen.getByRole('button', { name: 'save' }));

    expect(mockPersonasApi.create).not.toHaveBeenCalled();
    expect(toast.warning).toHaveBeenCalledWith('personality.validation.missing');
  });
});
