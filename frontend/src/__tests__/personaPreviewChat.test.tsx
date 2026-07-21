import { useState, type ComponentProps } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  PersonaPreviewChat,
  type CustomPersonaDraft,
} from '../components/onboarding/PersonaPreviewChat';
import { personasApi, type SeedPreview, type PersonalityConfig } from '../api/modules/personas';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'zh-CN' },
  }),
}));

// Mock the streaming client so tests don't hit the network
const mockStream = vi.fn();
vi.mock('../api/modules/chatPreview', () => ({
  streamChatPreview: (...args: any[]) => mockStream(...args),
}));

function makeAsyncIter(chunks: string[]) {
  return (async function* () {
    for (const c of chunks) yield c;
  })();
}

const previews: SeedPreview[] = [
  {
    seed_slug: 'nova',
    name: 'Nova',
    description: 'Polished assistant',
    avatar: '/avatars/nova.png',
    group: 'en',
    order: 0,
  },
  {
    seed_slug: 'ember',
    name: 'Ember',
    description: 'Deep listener',
    avatar: '/avatars/ember.png',
    group: 'en',
    order: 1,
  },
];

type ControlledPersonaPreviewProps = Omit<
  ComponentProps<typeof PersonaPreviewChat>,
  | 'activeSeed'
  | 'onActiveSeedChange'
  | 'previewsLoading'
  | 'disabled'
  | 'confirmationError'
> & {
  initialActiveSeed?: string | null;
  onActiveSeedChange?: (seedSlug: string | null) => void;
  previewsLoading?: boolean;
  disabled?: boolean;
  confirmationError?: string | null;
};

function ControlledPersonaPreview({
  initialActiveSeed = 'nova',
  onActiveSeedChange,
  previewsLoading = false,
  disabled = false,
  confirmationError = null,
  ...props
}: ControlledPersonaPreviewProps): JSX.Element {
  const [activeSeed, setActiveSeed] = useState<string | null>(initialActiveSeed);

  return (
    <PersonaPreviewChat
      {...props}
      activeSeed={activeSeed}
      previewsLoading={previewsLoading}
      disabled={disabled}
      confirmationError={confirmationError}
      onActiveSeedChange={(seedSlug) => {
        setActiveSeed(seedSlug);
        onActiveSeedChange?.(seedSlug);
      }}
    />
  );
}

function renderPersonaPreview(props: ControlledPersonaPreviewProps & { stayInPicker?: boolean }) {
  const { stayInPicker, ...rest } = props;
  const utils = render(<ControlledPersonaPreview {...rest} />);
  // The step is now two-stage (picker → detail); most tests exercise the
  // detail view, so enter it by clicking the active seed's picker card.
  if (!stayInPicker) {
    const seed = rest.initialActiveSeed ?? 'nova';
    const card = screen.queryByTestId(`persona-pick-${seed}`);
    if (card) {
      fireEvent.click(card);
    }
  }
  return utils;
}

describe('PersonaPreviewChat', () => {
  beforeEach(() => {
    mockStream.mockReset();
    mockStream.mockImplementation(() => makeAsyncIter(['hello', ' ', 'world']));
    vi.spyOn(personasApi, 'resolveGenerationIntent').mockResolvedValue({
      success: true,
      message: 'ok',
      data: {
        status: 'original',
        candidates: [],
        selected_candidate_id: null,
        confidence: 0.96,
        requires_confirmation: false,
        explicit_constraints: [],
      },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders a picker card for every seed preview', () => {
    renderPersonaPreview({ previews, stayInPicker: true });
    expect(screen.getByRole('button', { name: /Nova/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Ember/i })).toBeInTheDocument();
  });

  it('opens in the picker stage with large persona cards and no chat composer', () => {
    renderPersonaPreview({ previews, stayInPicker: true });

    expect(screen.getByTestId('persona-pick-nova')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('persona-pick-ember')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByTestId('persona-create-custom')).toBeInTheDocument();
    expect(screen.queryByTestId('persona-back-to-picker')).not.toBeInTheDocument();
    expect(screen.queryByTestId('persona-mode-chat')).not.toBeInTheDocument();
  });

  it('enters the detail stage after picking a persona and returns via the back button', async () => {
    const user = userEvent.setup();
    renderPersonaPreview({ previews, stayInPicker: true });

    await user.click(screen.getByTestId('persona-pick-ember'));
    expect(await screen.findByTestId('persona-back-to-picker')).toBeInTheDocument();
    expect(screen.getByTestId('persona-mode-chat')).toBeInTheDocument();
    expect(screen.queryByTestId('persona-pick-nova')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('persona-back-to-picker'));
    expect(await screen.findByTestId('persona-pick-ember')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByTestId('persona-mode-chat')).not.toBeInTheDocument();
  });

  it('keeps the parent-selected persona active', () => {
    renderPersonaPreview({ previews, initialActiveSeed: 'ember', stayInPicker: true });

    expect(screen.getByRole('button', { name: /Ember/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: /Nova/i })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('keeps chat as the default and loads the selected builtin profile on demand', async () => {
    const profileConfig: PersonalityConfig = {
      ...makeGeneratedConfig(),
      name: 'Nova',
      description: 'Polished and precise',
      identity_core: {
        ...makeGeneratedConfig().identity_core,
        identity_statement: 'A precise assistant with a guarded honest streak.',
        values_loved: ['clarity'],
      },
      persona_layers: [
        { layer_id: 'surface', unlock_condition: null, modifiers: {} },
        {
          layer_id: 'crack',
          unlock_condition: { interaction_count_gte: 20 },
          modifiers: { behavior_shifts: ['Shares a more candid observation.'] },
        },
      ],
    };
    const presetSpy = vi.spyOn(personasApi, 'getPresetConfig').mockResolvedValue({
      success: true,
      message: 'ok',
      data: profileConfig,
    });

    renderPersonaPreview({ previews });

    expect(screen.getByTestId('persona-mode-chat')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByPlaceholderText(/composerPlaceholder/i)).toBeInTheDocument();
    expect(presetSpy).not.toHaveBeenCalled();

    await userEvent.click(screen.getByTestId('persona-mode-profile'));

    expect(await screen.findByTestId('persona-profile-panel')).toBeInTheDocument();
    expect(screen.getByText('A precise assistant with a guarded honest streak.')).toBeInTheDocument();
    expect(presetSpy).toHaveBeenCalledWith('nova', 'en');
    expect(screen.queryByPlaceholderText(/composerPlaceholder/i)).not.toBeInTheDocument();

    const layersToggle = screen.getByRole('button', {
      name: 'personality.sections.personaLayers',
    });
    expect(layersToggle).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(layersToggle);
    expect(layersToggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.queryByText('Shares a more candid observation.')).not.toBeInTheDocument();
    await userEvent.click(screen.getByTestId('persona-profile-reveal-layers'));
    expect(screen.getByText('Shares a more candid observation.')).toBeInTheDocument();
  });

  it('opens one profile section at a time and scrolls the new section into view', async () => {
    const scrollToMock = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: scrollToMock,
    });
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callback(0);
      return 1;
    });
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
    vi.spyOn(personasApi, 'getPresetConfig').mockResolvedValue({
      success: true,
      message: 'ok',
      data: { ...makeGeneratedConfig(), name: 'Nova' },
    });
    renderPersonaPreview({ previews });

    await userEvent.click(screen.getByTestId('persona-mode-profile'));

    const identityToggle = await screen.findByRole('button', {
      name: 'personality.sections.identityCore',
    });
    const voiceToggle = screen.getByRole('button', {
      name: 'personality.sections.idiolect',
    });
    expect(identityToggle).toHaveAttribute('aria-expanded', 'true');
    expect(voiceToggle).toHaveAttribute('aria-expanded', 'false');

    await userEvent.click(voiceToggle);

    expect(identityToggle).toHaveAttribute('aria-expanded', 'false');
    expect(voiceToggle).toHaveAttribute('aria-expanded', 'true');
    expect(scrollToMock).toHaveBeenCalledWith({
      top: 0,
      behavior: 'smooth',
    });
  });

  it('falls back to scrollTop when element scrolling is unavailable', async () => {
    const scrollToDescriptor = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'scrollTo',
    );
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: undefined,
    });
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callback(0);
      return 1;
    });
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
    vi.spyOn(personasApi, 'getPresetConfig').mockResolvedValue({
      success: true,
      message: 'ok',
      data: { ...makeGeneratedConfig(), name: 'Nova' },
    });
    try {
      renderPersonaPreview({ previews });

      await userEvent.click(screen.getByTestId('persona-mode-profile'));

      const panel = await screen.findByTestId('persona-profile-panel');
      panel.scrollTop = 42;
      const voiceToggle = screen.getByRole('button', {
        name: 'personality.sections.idiolect',
      });

      await userEvent.click(voiceToggle);

      expect(panel.scrollTop).toBe(30);
    } finally {
      if (scrollToDescriptor) {
        Object.defineProperty(HTMLElement.prototype, 'scrollTo', scrollToDescriptor);
      } else {
        delete (HTMLElement.prototype as { scrollTo?: unknown }).scrollTo;
      }
    }
  });

  it('preserves the trial transcript while switching between chat and profile', async () => {
    vi.spyOn(personasApi, 'getPresetConfig').mockResolvedValue({
      success: true,
      message: 'ok',
      data: { ...makeGeneratedConfig(), name: 'Nova' },
    });
    renderPersonaPreview({ previews });

    await userEvent.type(screen.getByPlaceholderText(/composerPlaceholder/i), 'keep-this');
    await userEvent.click(screen.getByRole('button', { name: /^(personaPreview\.)?send$/i }));
    await waitFor(() => expect(screen.getByText('keep-this')).toBeInTheDocument());

    await userEvent.click(screen.getByTestId('persona-mode-profile'));
    expect(await screen.findByTestId('persona-profile-panel')).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('persona-mode-chat'));

    expect(screen.getByText('keep-this')).toBeInTheDocument();
    expect(screen.getByText('hello world')).toBeInTheDocument();
  });

  it('shows a custom persona profile from its existing draft without another request', async () => {
    const presetSpy = vi.spyOn(personasApi, 'getPresetConfig');
    const customDraft: CustomPersonaDraft = {
      personaId: '11111111-1111-4111-8111-111111111111',
      slug: 'custom-1',
      name: 'Sage',
      description: 'wise mentor',
      config: makeGeneratedConfig(),
    };

    renderPersonaPreview({
      previews,
      initialActiveSeed: 'custom-1',
      initialCustomPersonas: [customDraft],
    });

    await userEvent.click(screen.getByTestId('persona-mode-profile'));

    expect(screen.getByTestId('persona-profile-panel')).toBeInTheDocument();
    expect(screen.getByText('a patient mentor')).toBeInTheDocument();
    expect(presetSpy).not.toHaveBeenCalled();
  });

  it('offers a retry when a builtin profile cannot be loaded', async () => {
    const presetSpy = vi
      .spyOn(personasApi, 'getPresetConfig')
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({
        success: true,
        message: 'ok',
        data: { ...makeGeneratedConfig(), name: 'Nova' },
      });
    renderPersonaPreview({ previews });

    await userEvent.click(screen.getByTestId('persona-mode-profile'));
    expect(await screen.findByTestId('persona-profile-error')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'personaPreview.profileRetry' }));
    expect(await screen.findByTestId('persona-profile-panel')).toBeInTheDocument();
    expect(presetSpy).toHaveBeenCalledTimes(2);
  });

  it('preserves a parent selection while previews are temporarily empty and after it loads', async () => {
    const onActiveSeedChange = vi.fn();
    const { rerender } = render(
      <PersonaPreviewChat
        previews={[]}
        previewsLoading
        activeSeed="ember"
        disabled={false}
        confirmationError={null}
        onActiveSeedChange={onActiveSeedChange}
      />,
    );

    await waitFor(() => expect(onActiveSeedChange).not.toHaveBeenCalled());

    rerender(
      <PersonaPreviewChat
        previews={previews}
        previewsLoading={false}
        activeSeed="ember"
        disabled={false}
        confirmationError={null}
        onActiveSeedChange={onActiveSeedChange}
      />,
    );

    expect(screen.getByRole('button', { name: /Ember/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(onActiveSeedChange).not.toHaveBeenCalled();
  });

  it('requests the first persona only after a non-empty list confirms the selection is missing', async () => {
    const onActiveSeedChange = vi.fn();
    const { rerender } = render(
      <PersonaPreviewChat
        previews={[]}
        previewsLoading
        activeSeed="missing"
        disabled={false}
        confirmationError={null}
        onActiveSeedChange={onActiveSeedChange}
      />,
    );

    await waitFor(() => expect(onActiveSeedChange).not.toHaveBeenCalled());

    rerender(
      <PersonaPreviewChat
        previews={previews}
        previewsLoading={false}
        activeSeed="missing"
        disabled={false}
        confirmationError={null}
        onActiveSeedChange={onActiveSeedChange}
      />,
    );

    await waitFor(() => expect(onActiveSeedChange).toHaveBeenCalledTimes(1));
    expect(onActiveSeedChange).toHaveBeenCalledWith('nova');
  });

  it('streams the persona reply and forwards the locale + llm_override', async () => {
    const llmConfig = { providers: {}, selections: {} } as any;
    renderPersonaPreview({ previews, locale: 'zh', llmConfig });
    const input = screen.getByPlaceholderText(/composerPlaceholder/i);
    await userEvent.type(input, 'hi');
    await userEvent.click(screen.getByRole('button', { name: /^(personaPreview\.)?send$/i }));
    await waitFor(() => {
      expect(screen.getByText(/hello world/i)).toBeInTheDocument();
    });
    expect(mockStream).toHaveBeenCalledWith(
      expect.objectContaining({
        seed_slug: 'nova',
        locale: 'zh',
        message: { role: 'user', content: 'hi' },
        llm_override: llmConfig,
      }),
    );
  });

  it('shows a typing indicator while waiting, then swaps it for the streamed reply', async () => {
    // Gate the stream so the assistant turn stays empty until we release it.
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    mockStream.mockImplementation(() =>
      (async function* () {
        await gate;
        yield 'hello world';
      })(),
    );

    renderPersonaPreview({ previews });
    await userEvent.type(screen.getByPlaceholderText(/composerPlaceholder/i), 'hi');
    await userEvent.click(screen.getByRole('button', { name: /^(personaPreview\.)?send$/i }));

    // Before the first chunk lands, the empty bubble shows typing dots, not text.
    expect(await screen.findByRole('status')).toBeInTheDocument();
    expect(screen.queryByText(/hello world/i)).not.toBeInTheDocument();

    // Once the reply streams in, the indicator is replaced by the text.
    release();
    await waitFor(() => expect(screen.getByText(/hello world/i)).toBeInTheDocument());
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('preserves each persona transcript when switching back and forth', async () => {
    renderPersonaPreview({ previews });
    // Send a message to Nova
    await userEvent.type(
      screen.getByPlaceholderText(/composerPlaceholder/i),
      'nova-msg',
    );
    await userEvent.click(screen.getByRole('button', { name: /^(personaPreview\.)?send$/i }));
    await waitFor(() => expect(screen.getByText('nova-msg')).toBeInTheDocument());

    // Switch to Ember, then back to Nova — nova-msg must still be there
    await userEvent.click(screen.getByTestId('persona-back-to-picker'));
    await userEvent.click(await screen.findByTestId('persona-pick-ember'));
    expect(screen.queryByText('nova-msg')).not.toBeInTheDocument();
    await userEvent.click(screen.getByTestId('persona-back-to-picker'));
    await userEvent.click(await screen.findByTestId('persona-pick-nova'));
    expect(screen.getByText('nova-msg')).toBeInTheDocument();
  });

  it('reports a persona slug when the user changes the selection', async () => {
    const onActiveSeedChange = vi.fn();
    renderPersonaPreview({ previews, onActiveSeedChange, stayInPicker: true });

    expect(onActiveSeedChange).not.toHaveBeenCalled();
    await userEvent.click(screen.getByTestId('persona-pick-ember'));
    await waitFor(() =>
      expect(onActiveSeedChange).toHaveBeenLastCalledWith('ember'),
    );
  });

  function makeGeneratedConfig(): PersonalityConfig {
    return {
      name: 'Sage',
      avatar: '',
      description: 'wise mentor',
      appearance_prompt: '',
      identity_core: {
        identity_statement: 'a patient mentor',
        values_loved: [],
        values_rejected: [],
        attention_biases: [],
      },
      idiolect: {
        sentence_style: 'measured and kind',
        vocab_available: [],
        vocab_avoided: [],
        structural_quirks: [],
        chattiness: 0.8,
      },
      registers: {},
      quiet_hours: [],
      signature_triggers: [],
      persona_layers: [],
      dynamic_state_rules: {},
      milestone_conditions: {},
      interim_lines: {},
      bootstrap: null,
    };
  }

  it('does not replace a restored builtin persona while its previews are loading', async () => {
    const onActiveSeedChange = vi.fn();
    const customDraft: CustomPersonaDraft = {
      personaId: '11111111-1111-4111-8111-111111111111',
      slug: 'custom-1',
      name: 'Sage',
      description: 'wise mentor',
      config: makeGeneratedConfig(),
    };

    render(
      <PersonaPreviewChat
        previews={[]}
        previewsLoading
        activeSeed="ember"
        disabled={false}
        confirmationError={null}
        initialCustomPersonas={[customDraft]}
        onActiveSeedChange={onActiveSeedChange}
      />,
    );

    expect(screen.getByRole('button', { name: /Sage/i })).toBeInTheDocument();
    await waitFor(() => expect(onActiveSeedChange).not.toHaveBeenCalled());
  });

  it('generates a custom persona and chats with it via persona_override', async () => {
    const personaId = '11111111-1111-4111-8111-111111111111';
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(personaId);
    const generated = makeGeneratedConfig();
    const genSpy = vi
      .spyOn(personasApi, 'generateWithProgress')
      .mockResolvedValue({ success: true, message: 'ok', data: generated, stages: [] } as any);
    const onCustomPersonasChange = vi.fn();
    const llmConfig = { providers: {}, selections: {} } as any;

    renderPersonaPreview({ previews, llmConfig, onCustomPersonasChange, stayInPicker: true });

    // Open the custom composer, describe, and generate.
    await userEvent.click(screen.getByTestId('persona-create-custom'));
    await userEvent.type(screen.getByTestId('persona-custom-description'), 'a wise mentor');
    await userEvent.click(screen.getByTestId('persona-custom-generate'));

    await waitFor(() => expect(genSpy).toHaveBeenCalled());
    expect(genSpy.mock.calls[0][0]).toEqual(
      expect.objectContaining({ description: 'a wise mentor', llm_override: llmConfig }),
    );

    // The parent is told about the new draft.
    await waitFor(() => expect(onCustomPersonasChange).toHaveBeenCalled());
    const calls = onCustomPersonasChange.mock.calls;
    const lastDrafts = calls[calls.length - 1][0];
    expect(lastDrafts).toHaveLength(1);
    expect(lastDrafts[0]).toEqual(
      expect.objectContaining({
        personaId,
        slug: `onboarding-custom-${personaId}`,
        name: 'Sage',
        config: generated,
      }),
    );

    // The new persona is auto-selected; sending a message uses persona_override.
    const input = await screen.findByPlaceholderText(/composerPlaceholder/i);
    await userEvent.type(input, 'hi');
    await userEvent.click(screen.getByRole('button', { name: /^(personaPreview\.)?send$/i }));

    await waitFor(() => {
      expect(mockStream).toHaveBeenCalledWith(
        expect.objectContaining({
          persona_override: generated,
          llm_override: llmConfig,
        }),
      );
    });
  });

  it('requires the user to choose between ambiguous character sources', async () => {
    vi.mocked(personasApi.resolveGenerationIntent).mockResolvedValueOnce({
      success: true,
      message: 'ok',
      data: {
        status: 'ambiguous',
        candidates: [
          {
            candidate_id: 'candidate-1',
            source_kind: 'fictional_reference',
            name: '孙悟空',
            work_title: '西游记',
            version: null,
            context: null,
            confidence: 0.52,
          },
          {
            candidate_id: 'candidate-2',
            source_kind: 'fictional_reference',
            name: '孙悟空',
            work_title: '龙珠',
            version: null,
            context: null,
            confidence: 0.46,
          },
        ],
        selected_candidate_id: null,
        confidence: 0.52,
        requires_confirmation: true,
        explicit_constraints: [],
      },
    });
    const genSpy = vi
      .spyOn(personasApi, 'generateWithProgress')
      .mockResolvedValue({
        success: true,
        message: 'ok',
        data: makeGeneratedConfig(),
        stages: [],
      } as any);

    renderPersonaPreview({ previews, stayInPicker: true });
    await userEvent.click(screen.getByTestId('persona-create-custom'));
    await userEvent.type(screen.getByTestId('persona-custom-description'), '孙悟空');
    await userEvent.click(screen.getByTestId('persona-custom-generate'));

    expect(await screen.findByTestId('persona-reference-editor')).toBeInTheDocument();
    expect(genSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId('persona-custom-generate')).toBeDisabled();

    await userEvent.click(screen.getByTestId('persona-reference-candidate-candidate-2'));
    expect(screen.getByTestId('persona-reference-work')).toHaveValue('龙珠');
    await userEvent.clear(screen.getByTestId('persona-reference-work'));
    await userEvent.type(screen.getByTestId('persona-reference-work'), '龙珠 Z');
    await userEvent.click(screen.getByTestId('persona-custom-generate'));

    await waitFor(() => expect(genSpy).toHaveBeenCalledTimes(1));
    expect(genSpy.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        intent: expect.objectContaining({
          source_kind: 'fictional_reference',
          adaptation_mode: 'fictional_natural',
          expression_profile: 'natural',
          reference: expect.objectContaining({
            name: '孙悟空',
            work_title: '龙珠 Z',
            user_confirmed: true,
          }),
        }),
      }),
    );
  });

  it('locks persona creation while reference resolution is pending', async () => {
    let finishResolution: (value: unknown) => void = () => {};
    const resolutionSpy = vi
      .mocked(personasApi.resolveGenerationIntent)
      .mockImplementation(
        () =>
          new Promise((resolve) => {
            finishResolution = resolve;
          }) as any,
      );

    function ParentRerenderHarness(): JSX.Element {
      const [, setSavedCreationDraft] = useState<unknown>(null);
      return (
        <ControlledPersonaPreview
          previews={previews}
          onCreationDraftChange={(draft) => setSavedCreationDraft(draft)}
        />
      );
    }

    render(<ParentRerenderHarness />);
    await userEvent.click(screen.getByTestId('persona-create-custom'));
    await userEvent.type(screen.getByTestId('persona-custom-description'), '孙悟空');

    const generateButton = screen.getByTestId('persona-custom-generate');
    await act(async () => {
      generateButton.click();
      generateButton.click();
      await Promise.resolve();
    });

    expect(resolutionSpy).toHaveBeenCalledTimes(1);
    expect(generateButton).toBeDisabled();
    expect(generateButton).toHaveAttribute('aria-busy', 'true');
    expect(generateButton).toHaveTextContent('personaPreview.reference.resolving');
    expect(screen.getByTestId('persona-custom-description')).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'personaPreview.cancelCreate' }),
    ).toBeDisabled();

    finishResolution({
      success: true,
      message: 'ok',
      data: {
        status: 'ambiguous',
        candidates: [
          {
            candidate_id: 'candidate-1',
            source_kind: 'fictional_reference',
            name: '孙悟空',
            work_title: '西游记',
            version: null,
            context: null,
            confidence: 0.8,
          },
          {
            candidate_id: 'candidate-2',
            source_kind: 'fictional_reference',
            name: '孙悟空',
            work_title: '龙珠',
            version: null,
            context: null,
            confidence: 0.7,
          },
        ],
        selected_candidate_id: null,
        confidence: 0.8,
        requires_confirmation: true,
        explicit_constraints: [],
      },
    });
    await waitFor(() =>
      expect(screen.getByTestId('persona-reference-editor')).toBeInTheDocument(),
    );
  });

  it('lets the user edit a resolved work and choose immersive fidelity', async () => {
    vi.mocked(personasApi.resolveGenerationIntent).mockResolvedValueOnce({
      success: true,
      message: 'ok',
      data: {
        status: 'resolved',
        candidates: [
          {
            candidate_id: 'candidate-1',
            source_kind: 'fictional_reference',
            name: '孙悟空',
            work_title: '龙珠',
            version: null,
            context: null,
            confidence: 0.96,
          },
        ],
        selected_candidate_id: 'candidate-1',
        confidence: 0.96,
        requires_confirmation: true,
        explicit_constraints: ['少说设定黑话'],
      },
    });
    const generated = makeGeneratedConfig();
    const genSpy = vi.spyOn(personasApi, 'generateWithProgress').mockResolvedValue({
      success: true,
      message: 'ok',
      data: generated,
      stages: [],
    } as any);

    renderPersonaPreview({ previews, stayInPicker: true });
    await userEvent.click(screen.getByTestId('persona-create-custom'));
    await userEvent.type(screen.getByTestId('persona-custom-description'), '龙珠里的孙悟空');
    await userEvent.click(screen.getByTestId('persona-custom-generate'));

    expect(await screen.findByTestId('persona-reference-work')).toHaveValue('龙珠');
    expect(screen.getByTestId('persona-reference-constraints')).toHaveValue('少说设定黑话');
    expect(screen.getByTestId('persona-custom-description-summary')).toHaveTextContent(
      '龙珠里的孙悟空',
    );
    expect(screen.getByTestId('persona-custom-description')).toBeDisabled();
    expect(screen.getByTestId('persona-reference-source-kind').tagName).toBe('BUTTON');
    expect(screen.getByTestId('persona-reference-advanced-toggle')).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    await userEvent.click(screen.getByTestId('persona-reference-advanced-toggle'));
    expect(screen.getByTestId('persona-reference-constraints')).toBeEnabled();
    await userEvent.click(screen.getByTestId('persona-custom-description-edit'));
    expect(screen.getByTestId('persona-custom-description')).toBeEnabled();
    await userEvent.click(screen.getByTestId('persona-reference-mode-fictional_immersive'));
    await userEvent.click(screen.getByTestId('persona-custom-generate'));

    await waitFor(() => expect(genSpy).toHaveBeenCalledTimes(1));
    expect(genSpy.mock.calls[0][0].intent).toEqual(
      expect.objectContaining({
        adaptation_mode: 'fictional_immersive',
        expression_profile: 'immersive',
        explicit_constraints: ['少说设定黑话'],
      }),
    );
  });

  it('reopens a generated reference for correction without changing its persona id', async () => {
    const generated = makeGeneratedConfig();
    const customDraft: CustomPersonaDraft = {
      personaId: '11111111-1111-4111-8111-111111111111',
      slug: 'custom-1',
      name: 'Goku',
      description: 'natural Goku',
      originalDescription: '孙悟空',
      revision: 1,
      intent: {
        source_kind: 'fictional_reference',
        reference: {
          source_kind: 'fictional_reference',
          name: '孙悟空',
          work_title: '西游记',
          version: null,
          context: null,
          user_confirmed: true,
        },
        adaptation_mode: 'fictional_natural',
        expression_profile: 'natural',
        explicit_constraints: [],
      },
      config: generated,
    };
    const onCustomPersonasChange = vi.fn();
    const genSpy = vi.spyOn(personasApi, 'generateWithProgress').mockResolvedValue({
      success: true,
      message: 'ok',
      data: { ...generated, name: 'Dragon Goku' },
      stages: [],
    } as any);

    renderPersonaPreview({
      previews,
      initialActiveSeed: 'custom-1',
      initialCustomPersonas: [customDraft],
      onCustomPersonasChange,
    });

    const composer = screen.getByPlaceholderText(/composerPlaceholder/i);
    await userEvent.type(composer, 'old source question');
    await userEvent.click(screen.getByRole('button', { name: /^(personaPreview\.)?send$/i }));
    expect(await screen.findByText('hello world')).toBeInTheDocument();

    expect(screen.getByTestId('persona-reference-summary')).toHaveTextContent('西游记');
    await userEvent.click(screen.getByTestId('persona-reference-edit'));
    await userEvent.clear(screen.getByTestId('persona-reference-work'));
    await userEvent.type(screen.getByTestId('persona-reference-work'), '龙珠');
    await userEvent.click(screen.getByTestId('persona-custom-generate'));

    await waitFor(() => expect(genSpy).toHaveBeenCalledTimes(1));
    expect(screen.queryByText('old source question')).not.toBeInTheDocument();
    expect(screen.queryByText('hello world')).not.toBeInTheDocument();
    const draftCalls = onCustomPersonasChange.mock.calls;
    const lastDrafts = draftCalls[draftCalls.length - 1]?.[0] as CustomPersonaDraft[];
    expect(lastDrafts).toHaveLength(1);
    expect(lastDrafts[0]).toEqual(
      expect.objectContaining({
        personaId: customDraft.personaId,
        slug: customDraft.slug,
        revision: 2,
      }),
    );
    expect(lastDrafts[0].intent?.reference?.work_title).toBe('龙珠');
  });

  it('adjusts a custom persona separately and re-answers the last preview turn', async () => {
    const originalConfig = makeGeneratedConfig();
    const adjustedConfig = {
      ...originalConfig,
      idiolect: {
        ...originalConfig.idiolect,
        sentence_style: 'short and natural',
        chattiness: 0.2,
      },
    };
    const customDraft: CustomPersonaDraft = {
      personaId: '11111111-1111-4111-8111-111111111111',
      slug: 'custom-1',
      name: 'Sage',
      description: 'wise mentor',
      originalDescription: 'a wise mentor',
      revision: 1,
      config: originalConfig,
    };
    const adjustSpy = vi.spyOn(personasApi, 'adjust').mockResolvedValue({
      success: true,
      message: 'ok',
      data: adjustedConfig,
    });
    const onCustomPersonasChange = vi.fn();
    mockStream
      .mockImplementationOnce(() => makeAsyncIter(['old reply']))
      .mockImplementationOnce(() => makeAsyncIter(['new short reply']))
      .mockImplementationOnce(() => makeAsyncIter(['next reply']));

    renderPersonaPreview({
      previews,
      initialActiveSeed: 'custom-1',
      initialCustomPersonas: [customDraft],
      onCustomPersonasChange,
    });

    const composer = screen.getByPlaceholderText(/composerPlaceholder/i);
    await userEvent.type(composer, 'first question');
    await userEvent.click(screen.getByRole('button', { name: /^(personaPreview\.)?send$/i }));
    expect(await screen.findByText('old reply')).toBeInTheDocument();

    await userEvent.type(
      screen.getByTestId('persona-adjustment-input'),
      '回复短一点',
    );
    await userEvent.click(screen.getByTestId('persona-adjustment-submit'));

    expect(await screen.findByTestId('persona-adjustment-divider')).toBeInTheDocument();
    expect(await screen.findByText('new short reply')).toBeInTheDocument();
    expect(screen.getByText('old reply')).toBeInTheDocument();
    expect(adjustSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        current_config: originalConfig,
        instruction: '回复短一点',
        scope: 'auto',
      }),
    );
    const draftCalls = onCustomPersonasChange.mock.calls;
    const adjustedDrafts = draftCalls[draftCalls.length - 1][0] as CustomPersonaDraft[];
    expect(adjustedDrafts[0].revision).toBe(2);
    expect(adjustedDrafts[0].config).toBe(adjustedConfig);

    await userEvent.type(composer, 'next question');
    await userEvent.click(screen.getByRole('button', { name: /^(personaPreview\.)?send$/i }));
    await waitFor(() => expect(mockStream).toHaveBeenCalledTimes(3));
    expect(mockStream.mock.calls[2][0].history).toEqual([
      { role: 'user', content: 'first question' },
      { role: 'assistant', content: 'new short reply' },
    ]);
    expect(mockStream.mock.calls[2][0].persona_override).toBe(adjustedConfig);
  });

  it('blocks chat input while a persona adjustment is still running', async () => {
    const originalConfig = makeGeneratedConfig();
    const customDraft: CustomPersonaDraft = {
      personaId: '11111111-1111-4111-8111-111111111111',
      slug: 'custom-1',
      name: 'Sage',
      description: 'wise mentor',
      revision: 1,
      config: originalConfig,
    };
    let finishAdjustment: (value: unknown) => void = () => {};
    vi.spyOn(personasApi, 'adjust').mockImplementation(
      () =>
        new Promise((resolve) => {
          finishAdjustment = resolve;
        }) as any,
    );

    renderPersonaPreview({
      previews,
      initialActiveSeed: 'custom-1',
      initialCustomPersonas: [customDraft],
    });

    await userEvent.type(
      screen.getByTestId('persona-adjustment-input'),
      '回复短一点',
    );
    await userEvent.click(screen.getByTestId('persona-adjustment-submit'));

    const composer = screen.getByPlaceholderText(/composerPlaceholder/i);
    const sendButton = screen.getByRole('button', {
      name: /^(personaPreview\.)?send$/i,
    });
    expect(composer).toBeDisabled();
    expect(sendButton).toBeDisabled();

    finishAdjustment({
      success: true,
      message: 'ok',
      data: originalConfig,
    });
    await waitFor(() => expect(composer).not.toBeDisabled());
  });

  it('reveals rhythm segments over time and collapses them in history', async () => {
    let releaseSecondSegment: () => void = () => {};
    const secondSegmentGate = new Promise<void>((resolve) => {
      releaseSecondSegment = resolve;
    });
    mockStream
      .mockImplementationOnce(() =>
        (async function* () {
          yield 'first reply';
          await secondSegmentGate;
          yield '‖second reply';
        })(),
      )
      .mockImplementationOnce(() => makeAsyncIter(['third reply']));

    renderPersonaPreview({ previews });
    const input = screen.getByPlaceholderText(/composerPlaceholder/i);
    const sendButton = screen.getByRole('button', { name: /^(personaPreview\.)?send$/i });

    await userEvent.type(input, 'first question');
    await userEvent.click(sendButton);
    await waitFor(() => expect(screen.getByText('first reply')).toBeInTheDocument());

    expect(screen.getAllByTestId('persona-preview-assistant-bubble')).toHaveLength(1);
    expect(screen.queryByText('second reply')).not.toBeInTheDocument();
    await userEvent.type(input, 'second question');
    expect(sendButton).toBeDisabled();

    releaseSecondSegment();
    await waitFor(() => expect(screen.getByText('second reply')).toBeInTheDocument());
    expect(screen.getAllByTestId('persona-preview-assistant-bubble')).toHaveLength(2);
    await waitFor(() => expect(sendButton).toBeEnabled());

    await userEvent.click(sendButton);
    await waitFor(() => expect(screen.getByText('third reply')).toBeInTheDocument());

    expect(mockStream.mock.calls[1][0].history).toEqual([
      { role: 'user', content: 'first question' },
      { role: 'assistant', content: 'first reply\nsecond reply' },
    ]);
  });

  it('disables every persona control and keeps confirmation errors visible', () => {
    renderPersonaPreview({
      previews,
      ...({
        disabled: true,
        confirmationError: 'messages.personaActivationFailed',
      } as any),
    });

    expect(screen.getByRole('alert')).toHaveTextContent('messages.personaActivationFailed');
    expect(screen.getByRole('button', { name: /Nova/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Ember/i })).toBeDisabled();
    expect(screen.getByTestId('persona-create-custom')).toBeDisabled();
    // 禁用状态下 picker 卡片不可点,无法进入 detail。
    expect(screen.queryByTestId('persona-back-to-picker')).not.toBeInTheDocument();
  });

  it('shows a generation progress indicator while the persona is being built', async () => {
    let resolveGen: (value: any) => void = () => {};
    vi.spyOn(personasApi, 'generateWithProgress').mockImplementation(
      () => new Promise((resolve) => { resolveGen = resolve; }),
    );

    renderPersonaPreview({ previews, stayInPicker: true });
    await userEvent.click(screen.getByTestId('persona-create-custom'));
    await userEvent.type(screen.getByTestId('persona-custom-description'), 'x');
    await userEvent.click(screen.getByTestId('persona-custom-generate'));

    // While the job is in flight, a progress indicator is visible.
    expect(await screen.findByTestId('persona-generation-progress')).toBeInTheDocument();

    resolveGen({ success: true, message: 'ok', data: makeGeneratedConfig(), stages: [] });
    await waitFor(() =>
      expect(screen.queryByTestId('persona-generation-progress')).not.toBeInTheDocument(),
    );
  });

  it('localizes backend generation stage labels', async () => {
    let resolveGen: (value: any) => void = () => {};
    vi.spyOn(personasApi, 'generateWithProgress').mockImplementation(
      (_request, onProgress) => {
        onProgress?.({
          job_id: 'job-1',
          status: 'running',
          stages: [
            {
              stage_id: 'base',
              label: 'Understand persona spine',
              status: 'running',
            },
          ],
        });
        return new Promise((resolve) => { resolveGen = resolve; });
      },
    );

    renderPersonaPreview({ previews, stayInPicker: true });
    await userEvent.click(screen.getByTestId('persona-create-custom'));
    await userEvent.type(screen.getByTestId('persona-custom-description'), 'x');
    await userEvent.click(screen.getByTestId('persona-custom-generate'));

    expect(await screen.findByText('personaPreview.generationStages.base')).toBeInTheDocument();
    expect(screen.queryByText('Understand persona spine')).not.toBeInTheDocument();

    resolveGen({ success: true, message: 'ok', data: makeGeneratedConfig(), stages: [] });
  });

  it('marks the running generation stage with motion-friendly state', async () => {
    let resolveGen: (value: any) => void = () => {};
    vi.spyOn(personasApi, 'generateWithProgress').mockImplementation(
      (_request, onProgress) => {
        onProgress?.({
          job_id: 'job-1',
          status: 'running',
          stages: [
            { stage_id: 'base', status: 'completed' },
            { stage_id: 'registers', status: 'running' },
            { stage_id: 'rules', status: 'pending' },
          ],
        });
        return new Promise((resolve) => { resolveGen = resolve; });
      },
    );

    renderPersonaPreview({ previews, stayInPicker: true });
    await userEvent.click(screen.getByTestId('persona-create-custom'));
    await userEvent.type(screen.getByTestId('persona-custom-description'), 'x');
    await userEvent.click(screen.getByTestId('persona-custom-generate'));

    const runningStage = await screen.findByTestId('persona-generation-stage-running');
    expect(runningStage).toHaveAttribute('aria-current', 'step');
    expect(within(runningStage).getByTestId('persona-generation-stage-spinner')).toHaveClass('animate-spin');

    resolveGen({ success: true, message: 'ok', data: makeGeneratedConfig(), stages: [] });
  });

  it('reports generating state via onGeneratingChange', async () => {
    let resolveGen: (value: any) => void = () => {};
    vi.spyOn(personasApi, 'generateWithProgress').mockImplementation(
      () => new Promise((resolve) => { resolveGen = resolve; }),
    );
    const onGeneratingChange = vi.fn();

    renderPersonaPreview({ previews, onGeneratingChange, stayInPicker: true });
    await userEvent.click(screen.getByTestId('persona-create-custom'));
    await userEvent.type(screen.getByTestId('persona-custom-description'), 'x');
    await userEvent.click(screen.getByTestId('persona-custom-generate'));

    await waitFor(() => expect(onGeneratingChange).toHaveBeenLastCalledWith(true));

    resolveGen({ success: true, message: 'ok', data: makeGeneratedConfig(), stages: [] });
    await waitFor(() => expect(onGeneratingChange).toHaveBeenLastCalledWith(false));
  });

  it('disables input once the 5-turn cap is hit for the active persona', async () => {
    renderPersonaPreview({ previews });
    for (let i = 0; i < 5; i++) {
      await userEvent.type(
        screen.getByPlaceholderText(/composerPlaceholder/i),
        `m${i}`,
      );
      await userEvent.click(
        screen.getByRole('button', { name: /^(personaPreview\.)?send$/i }),
      );
      await waitFor(() =>
        expect(screen.getAllByText(/hello world/i).length).toBeGreaterThanOrEqual(i + 1),
      );
    }
    expect(
      screen.getByPlaceholderText(/composerPlaceholder/i),
    ).toBeDisabled();
  });
});
