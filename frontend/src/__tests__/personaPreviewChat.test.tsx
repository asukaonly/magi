import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { PersonaPreviewChat } from '../components/onboarding/PersonaPreviewChat';
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

describe('PersonaPreviewChat', () => {
  beforeEach(() => {
    mockStream.mockReset();
    mockStream.mockImplementation(() => makeAsyncIter(['hello', ' ', 'world']));
  });

  it('renders a rail entry for every seed preview', () => {
    render(<PersonaPreviewChat previews={previews} />);
    expect(screen.getByRole('button', { name: /Nova/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Ember/i })).toBeInTheDocument();
  });

  it('streams the persona reply and forwards the locale + llm_override', async () => {
    const llmConfig = { providers: {}, selections: {} } as any;
    render(<PersonaPreviewChat previews={previews} locale="zh" llmConfig={llmConfig} />);
    await userEvent.click(screen.getByRole('button', { name: /Nova/i }));
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

    render(<PersonaPreviewChat previews={previews} />);
    await userEvent.click(screen.getByRole('button', { name: /Nova/i }));
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
    render(<PersonaPreviewChat previews={previews} />);
    // Send a message to Nova
    await userEvent.click(screen.getByRole('button', { name: /Nova/i }));
    await userEvent.type(
      screen.getByPlaceholderText(/composerPlaceholder/i),
      'nova-msg',
    );
    await userEvent.click(screen.getByRole('button', { name: /^(personaPreview\.)?send$/i }));
    await waitFor(() => expect(screen.getByText('nova-msg')).toBeInTheDocument());

    // Switch to Ember, then back to Nova — nova-msg must still be there
    await userEvent.click(screen.getByRole('button', { name: /Ember/i }));
    expect(screen.queryByText('nova-msg')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Nova/i }));
    expect(screen.getByText('nova-msg')).toBeInTheDocument();
  });

  it('reports the active persona slug via onActiveSeedChange', async () => {
    const onActiveSeedChange = vi.fn();
    render(
      <PersonaPreviewChat
        previews={previews}
        onActiveSeedChange={onActiveSeedChange}
      />,
    );
    // Fires with the default (first) selection on mount.
    await waitFor(() =>
      expect(onActiveSeedChange).toHaveBeenCalledWith('nova'),
    );
    // Fires again when the user picks a different persona.
    await userEvent.click(screen.getByRole('button', { name: /Ember/i }));
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

  it('generates a custom persona and chats with it via persona_override', async () => {
    const generated = makeGeneratedConfig();
    const genSpy = vi
      .spyOn(personasApi, 'generateWithProgress')
      .mockResolvedValue({ success: true, message: 'ok', data: generated, stages: [] } as any);
    const onCustomPersonasChange = vi.fn();
    const llmConfig = { providers: {}, selections: {} } as any;

    render(
      <PersonaPreviewChat
        previews={previews}
        llmConfig={llmConfig}
        onCustomPersonasChange={onCustomPersonasChange}
      />,
    );

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
      expect.objectContaining({ name: 'Sage', config: generated }),
    );

    // The new persona is auto-selected; sending a message uses persona_override.
    const input = await screen.findByPlaceholderText(/composerPlaceholder/i);
    await userEvent.type(input, 'hi');
    await userEvent.click(screen.getByRole('button', { name: /^(personaPreview\.)?send$/i }));

    await waitFor(() => {
      expect(mockStream).toHaveBeenCalledWith(
        expect.objectContaining({
          persona_override: {
            name: 'Sage',
            identity_statement: 'a patient mentor',
            sentence_style: 'measured and kind',
          },
          llm_override: llmConfig,
        }),
      );
    });
  });

  it('shows a generation progress indicator while the persona is being built', async () => {
    let resolveGen: (value: any) => void = () => {};
    vi.spyOn(personasApi, 'generateWithProgress').mockImplementation(
      () => new Promise((resolve) => { resolveGen = resolve; }),
    );

    render(<PersonaPreviewChat previews={previews} />);
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

  it('reports generating state via onGeneratingChange', async () => {
    let resolveGen: (value: any) => void = () => {};
    vi.spyOn(personasApi, 'generateWithProgress').mockImplementation(
      () => new Promise((resolve) => { resolveGen = resolve; }),
    );
    const onGeneratingChange = vi.fn();

    render(
      <PersonaPreviewChat previews={previews} onGeneratingChange={onGeneratingChange} />,
    );
    await userEvent.click(screen.getByTestId('persona-create-custom'));
    await userEvent.type(screen.getByTestId('persona-custom-description'), 'x');
    await userEvent.click(screen.getByTestId('persona-custom-generate'));

    await waitFor(() => expect(onGeneratingChange).toHaveBeenLastCalledWith(true));

    resolveGen({ success: true, message: 'ok', data: makeGeneratedConfig(), stages: [] });
    await waitFor(() => expect(onGeneratingChange).toHaveBeenLastCalledWith(false));
  });

  it('disables input once the 5-turn cap is hit for the active persona', async () => {
    render(<PersonaPreviewChat previews={previews} />);
    await userEvent.click(screen.getByRole('button', { name: /Nova/i }));
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
