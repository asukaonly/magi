import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { PersonaPreviewChat } from '../components/onboarding/PersonaPreviewChat';
import type { SeedPreview } from '../api/modules/personas';

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

  it('renders avatar for every seed preview', () => {
    render(
      <PersonaPreviewChat
        previews={previews}
        onConfirm={() => {}}
      />,
    );
    expect(screen.getByRole('button', { name: /Nova/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Ember/i })).toBeInTheDocument();
  });

  it('streams the persona reply when user sends a message', async () => {
    render(
      <PersonaPreviewChat
        previews={previews}
        onConfirm={() => {}}
      />,
    );
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
        message: { role: 'user', content: 'hi' },
      }),
    );
  });

  it('preserves each persona transcript when switching back and forth', async () => {
    render(
      <PersonaPreviewChat
        previews={previews}
        onConfirm={() => {}}
      />,
    );
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

  it('confirms with the active persona slug', async () => {
    const onConfirm = vi.fn();
    render(
      <PersonaPreviewChat
        previews={previews}
        onConfirm={onConfirm}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /Ember/i }));
    await userEvent.click(
      screen.getByRole('button', { name: /^(personaPreview\.)?confirm$/i }),
    );
    expect(onConfirm).toHaveBeenCalledWith('ember');
  });

  it('disables input once the 5-turn cap is hit for the active persona', async () => {
    render(
      <PersonaPreviewChat
        previews={previews}
        onConfirm={() => {}}
      />,
    );
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
