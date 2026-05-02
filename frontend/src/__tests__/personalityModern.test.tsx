import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import PersonalityModern from '@/pages/PersonalityModern';
import { usePersonality } from '@/hooks';
import { personasApi } from '@/api/modules/personas';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/api/modules/personas', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/personas')>('@/api/modules/personas');
  return {
    ...actual,
    personasApi: {
      ...actual.personasApi,
      uploadAvatar: vi.fn(),
      getAvatarUrl: vi.fn((avatar?: string) => avatar || ''),
    },
  };
});

vi.mock('@/hooks', () => ({
  usePersonality: vi.fn(),
  CONFIDENCE_OPTIONS: ['Low', 'Medium', 'High'],
  parseLines: (value: string) => value.split('\n').filter(Boolean),
  toLines: (value: string[]) => value.join('\n'),
  getInitials: (value: string) => value.slice(0, 1),
  normalizeTrigger: (value: Record<string, string>) => ({
    trigger_id: '',
    activates_when: '',
    behavior_shift: '',
    intensity_levels: {},
    exit_behavior: '',
    ...value,
  }),
}));

const buildConfig = (name = '七号', description = '赛博乐子人 / 反讽大师') => ({
  name,
  description,
  avatar: '',
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

const buildHookState = (overrides: Partial<Record<string, unknown>> = {}) => ({
  config: buildConfig(),
  list: [
    { id: 'uuid-seven', name: '七号', displayName: '七号', subtitle: '赛博乐子人 / 反讽大师', avatar: '/static/user-avatars/seven.png' },
    { id: 'uuid-asuka', name: '明日香', displayName: '明日香', subtitle: '傲娇驾驶员', avatar: '' },
  ],
  currentId: 'uuid-seven',
  selectedId: 'uuid-seven',
  isNewMode: false,
  loading: false,
  saving: false,
  generating: false,
  switching: false,
  selectedInfo: { id: 'uuid-seven', name: '七号', displayName: '七号', subtitle: '赛博乐子人 / 反讽大师' },
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
  deleteConfirmOpen: false,
  requestDeletePersonality: vi.fn(),
  confirmDeletePersonality: vi.fn(),
  cancelDeletePersonality: vi.fn(),
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
        selectedId: 'uuid-asuka',
        selectedInfo: { id: 'uuid-asuka', name: '明日香', displayName: '明日香', subtitle: '傲娇驾驶员' },
        config: buildConfig('明日香', '傲娇驾驶员'),
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
        selectedId: '__new__',
        selectedInfo: undefined,
        config: buildConfig('', ''),
      }) as any
    );

    render(<PersonalityModern embedded />);

    const createCard = screen.getByTestId('personality-create-card');

    expect(createCard).toBeInTheDocument();
    expect(createCard.firstElementChild).toHaveClass('border-primary');
    expect(screen.getAllByText('personality.generate')).toHaveLength(2);
    expect(within(createCard).queryByText('personality.current')).not.toBeInTheDocument();
    expect(createCard.querySelectorAll('.lucide-check')).toHaveLength(0);
  });

  it('hides AI generation when editing an existing personality', () => {
    vi.mocked(usePersonality).mockReturnValue(buildHookState() as any);

    render(<PersonalityModern embedded />);

    expect(screen.queryAllByText('personality.generate')).toHaveLength(0);
  });

  it('starts the personality detail editor in a focused quick mode', () => {
    vi.mocked(usePersonality).mockReturnValue(
      buildHookState({
        isNewMode: true,
        selectedId: '__new__',
        selectedInfo: undefined,
        config: buildConfig('', ''),
      }) as any
    );

    render(<PersonalityModern embedded />);

    expect(screen.getByRole('tab', { name: 'personality.editorModes.quick' })).toHaveAttribute('data-state', 'active');
    expect(screen.queryByText('personality.validation.missing')).not.toBeInTheDocument();
    expect(screen.getByText('personality.fields.chatBehavior')).toBeInTheDocument();
    expect(screen.queryByText('personality.sections.signatureTriggers')).not.toBeInTheDocument();
    expect(screen.queryByText('personality.sections.quietHours')).not.toBeInTheDocument();
    expect(screen.queryByText('personality.registers.crisis')).not.toBeInTheDocument();
  });

  it('reveals full register and advanced sections in expert mode', () => {
    vi.mocked(usePersonality).mockReturnValue(buildHookState() as any);

    render(<PersonalityModern embedded />);

    fireEvent.pointerDown(screen.getByRole('tab', { name: 'personality.editorModes.expert' }), { button: 0 });
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'personality.editorModes.expert' }), { button: 0 });

    return waitFor(() => {
      expect(screen.getByRole('tab', { name: 'personality.editorModes.expert' })).toHaveAttribute('data-state', 'active');
    }).then(() => {
      expect(screen.getByText('personality.validation.missing')).toBeInTheDocument();
      expect(screen.getByText('personality.sections.registers')).toBeInTheDocument();
      expect(screen.getByText('personality.sections.appearance')).toBeInTheDocument();
      expect(screen.getByText('personality.sections.personaLayers')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'personality.sections.registers' }));
      expect(screen.getByText('personality.registers.crisis')).toBeInTheDocument();
    });
  });

  it('uploads an avatar and patches the personality profile', async () => {
    const patch = vi.fn();
    vi.mocked(usePersonality).mockReturnValue(buildHookState({ patch }) as any);
    vi.mocked(personasApi.uploadAvatar).mockResolvedValue({
      data: {
        url: '/static/user-avatars/test-avatar.png',
      },
    } as any);

    render(<PersonalityModern embedded />);

    const fileInput = screen.getByTestId('personality-avatar-input');
    const file = new File(['avatar'], 'avatar.png', { type: 'image/png' });

    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => expect(personasApi.uploadAvatar).toHaveBeenCalledWith(file));
    expect(patch).toHaveBeenCalledTimes(1);
    const draft = buildHookState().config;
    const updater = patch.mock.calls[0][0] as (value: typeof draft) => void;
    updater(draft);
    expect(draft.avatar).toBe('/static/user-avatars/test-avatar.png');
  });

  it('shows avatars in the selector cards before falling back to initials', () => {
    vi.mocked(usePersonality).mockReturnValue(buildHookState() as any);

    render(<PersonalityModern embedded />);

    expect(screen.getByAltText('七号')).toBeInTheDocument();
    expect(screen.getByText('明')).toBeInTheDocument();
  });
});
