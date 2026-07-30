import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { ImgHTMLAttributes } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import PersonalityModern from '@/components/personality/PersonalityModern';
import { usePersonality } from '@/hooks';
import { personasApi } from '@/api/modules/personas';

vi.mock('@/components/media/ProtectedImage', () => {
  const ProtectedImage = ({
    eager,
    onProtectedAccessError,
    ...imageProps
  }: ImgHTMLAttributes<HTMLImageElement> & {
    eager?: boolean;
    onProtectedAccessError?: () => void;
  }) => {
    void eager;
    void onProtectedAccessError;
    return <img {...imageProps} />;
  };
  return { ProtectedImage, default: ProtectedImage };
});

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

const buildConfig = (name = '七号', description = '嘴硬有梗，熟悉后会开始护短') => ({
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
    { id: 'uuid-seven', name: '七号', displayName: '七号', subtitle: '嘴硬有梗，熟悉后会开始护短', avatar: '/static/user-avatars/seven.png' },
    { id: 'uuid-asuka', name: '明日香', displayName: '明日香', subtitle: '傲娇驾驶员', avatar: '' },
  ],
  currentId: 'uuid-seven',
  selectedId: 'uuid-seven',
  isNewMode: false,
  loading: false,
  saving: false,
  generating: false,
  generationProgress: 0,
  generationStageKey: 'base',
  switching: false,
  selectedInfo: { id: 'uuid-seven', name: '七号', displayName: '七号', subtitle: '嘴硬有梗，熟悉后会开始护短' },
  switchPrompt: null,
  prompt: '',
  setPrompt: vi.fn(),
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

  it('keeps the avatar upload affordance icon-only', () => {
    vi.mocked(usePersonality).mockReturnValue(buildHookState() as any);

    render(<PersonalityModern embedded />);

    const uploadButton = screen.getByRole('button', { name: 'personality.actions.uploadAvatar' });
    expect(uploadButton.querySelector('.lucide-upload')).toBeInTheDocument();
    expect(screen.queryByText('personality.actions.uploadAvatar')).not.toBeInTheDocument();
    expect(screen.queryByText('personality.actions.uploadingAvatar')).not.toBeInTheDocument();
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
    expect(createCard).toHaveClass('bg-primary/10');
    expect(screen.getAllByText('personality.generate')).toHaveLength(2);
    expect(within(createCard).queryByText('personality.current')).not.toBeInTheDocument();
    expect(createCard.querySelectorAll('.lucide-check')).toHaveLength(0);
  });

  it('shows generation progress while generating a new personality', () => {
    vi.mocked(usePersonality).mockReturnValue(
      buildHookState({
        isNewMode: true,
        selectedId: '__new__',
        selectedInfo: undefined,
        config: buildConfig('', ''),
        generating: true,
        generationProgress: 43,
        generationStageKey: 'rules',
      }) as any
    );

    render(<PersonalityModern embedded />);

    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'personality.languages.auto' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'personality.generate' })).toBeDisabled();
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '43');
    expect(screen.getByText('personality.generationStages.rules')).toBeInTheDocument();
  });

  it('hides AI generation when editing an existing personality', () => {
    vi.mocked(usePersonality).mockReturnValue(buildHookState() as any);

    render(<PersonalityModern embedded />);

    expect(screen.queryAllByText('personality.generate')).toHaveLength(0);
  });

  it('renders the personality detail editor as a unified form', () => {
    vi.mocked(usePersonality).mockReturnValue(
      buildHookState({
        isNewMode: true,
        selectedId: '__new__',
        selectedInfo: undefined,
        config: buildConfig('', ''),
      }) as any
    );

    render(<PersonalityModern embedded />);

    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    expect(screen.queryByText('personality.validation.missing')).not.toBeInTheDocument();
    expect(screen.getByText('personality.sections.identityCore')).toBeInTheDocument();
    expect(screen.getByText('personality.sections.registers')).toBeInTheDocument();
    expect(screen.getByText('personality.sections.signatureTriggers')).toBeInTheDocument();
    expect(screen.getByText('personality.sections.quietHours')).toBeInTheDocument();
    expect(screen.getByText('personality.sections.personaLayers')).toBeInTheDocument();
    expect(screen.queryByText('personality.registers.crisis')).not.toBeInTheDocument();
  });

  it('reveals register and deep layer sections from the unified editor', () => {
    vi.mocked(usePersonality).mockReturnValue(
      buildHookState({
        config: {
          ...buildConfig(),
          persona_layers: [
            { layer_id: 'surface', unlock_condition: null, modifiers: {} },
            { layer_id: 'crack', unlock_condition: { trust_level_gte: 0.45 }, modifiers: { memory_behavior: 'light' } },
          ],
        },
      }) as any
    );

    render(<PersonalityModern embedded />);

    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    expect(screen.queryByText('personality.validation.missing')).not.toBeInTheDocument();
    expect(screen.getByText('personality.sections.registers')).toBeInTheDocument();
    expect(screen.getByText('personality.sections.appearance')).toBeInTheDocument();
    expect(screen.getByText('personality.sections.personaLayers')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('surface')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'personality.sections.registers' }));
    expect(screen.getByText('personality.registers.crisis')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'personality.sections.personaLayers' }));
    const confirmDialog = screen.getByRole('dialog');
    expect(confirmDialog.querySelector('.lucide-info')).toBeInTheDocument();
    expect(screen.getByTestId('personality-layer-confirm-actions')).not.toHaveClass('border-t');
    expect(screen.getByText('personality.actions.viewLayersConfirm')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('surface')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'personality.actions.viewLayersReveal' }));
    expect(screen.queryByDisplayValue('surface')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('crack')).toBeInTheDocument();
  });

  it('stacks identity core list fields and keeps help tips inside the editor', async () => {
    vi.mocked(usePersonality).mockReturnValue(buildHookState() as any);

    render(<PersonalityModern embedded />);
    if (!screen.queryByText('personality.fields.valuesLoved')) {
      fireEvent.click(screen.getByRole('button', { name: 'personality.sections.identityCore' }));
    }

    const lovedField = screen.getByText('personality.fields.valuesLoved').closest('label');
    const rejectedField = screen.getByText('personality.fields.valuesRejected').closest('label');
    const attentionField = screen.getByText('personality.fields.attentionBiases').closest('label');

    expect(lovedField).toHaveClass('block');
    expect(lovedField).toHaveClass('bg-muted/20');
    expect(rejectedField).toHaveClass('block');
    expect(attentionField).toHaveClass('block');

    const attentionHelp = screen.getByRole('button', {
      name: 'personality.fields.attentionBiases: personality.fieldHelp.attentionBiases',
    });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 });
    vi.spyOn(attentionHelp.parentElement as HTMLElement, 'getBoundingClientRect').mockReturnValue({
      left: 900,
      right: 916,
      top: 0,
      bottom: 16,
      width: 16,
      height: 16,
      x: 900,
      y: 0,
      toJSON: () => ({}),
    });

    fireEvent.mouseEnter(attentionHelp);
    expect(screen.getByRole('tooltip')).toHaveClass('right-0');
    expect(screen.getByRole('tooltip')).toHaveClass('break-words');
    fireEvent.mouseLeave(attentionHelp);
    await waitFor(() => {
      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    });
  });

  it('stacks voice list fields instead of squeezing them into columns', () => {
    vi.mocked(usePersonality).mockReturnValue(buildHookState() as any);

    render(<PersonalityModern embedded />);
    if (!screen.queryByText('personality.fields.vocabAvailable')) {
      fireEvent.click(screen.getByRole('button', { name: 'personality.sections.idiolect' }));
    }

    const availableField = screen.getByText('personality.fields.vocabAvailable').closest('label');
    const avoidedField = screen.getByText('personality.fields.vocabAvoided').closest('label');
    const quirksField = screen.getByText('personality.fields.structuralQuirks').closest('label');

    expect(availableField).toHaveClass('block');
    expect(availableField).toHaveClass('bg-muted/20');
    expect(avoidedField).toHaveClass('block');
    expect(quirksField).toHaveClass('block');
  });

  it('shows layer modifier help immediately and constrains modifier keys to supported options', async () => {
    vi.mocked(usePersonality).mockReturnValue(
      buildHookState({
        config: {
          ...buildConfig(),
          persona_layers: [
            { layer_id: 'surface', unlock_condition: null, modifiers: {} },
            { layer_id: 'crack', unlock_condition: { trust_level_gte: 0.45 }, modifiers: { memory_behavior: 'light' } },
          ],
        },
      }) as any
    );

    render(<PersonalityModern embedded />);

    fireEvent.click(screen.getByRole('button', { name: 'personality.sections.personaLayers' }));
    fireEvent.click(screen.getByRole('button', { name: 'personality.actions.viewLayersReveal' }));

    expect(screen.getByDisplayValue('crack')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'personality.fields.overrideKeyPlaceholder' })).not.toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'personality.fields.overrideKeyPlaceholder' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'memory_behavior' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'protective_bias' })).toBeInTheDocument();

    const layerModifiersHelp = screen.getByRole('button', {
      name: 'personality.fields.layerModifiers: personality.help.layerModifiers',
    });

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    fireEvent.mouseEnter(layerModifiersHelp);
    expect(screen.getByRole('tooltip')).toHaveTextContent('personality.help.layerModifiers');
    fireEvent.mouseLeave(layerModifiersHelp);
    await waitFor(() => {
      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
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
