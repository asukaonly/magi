import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { useChatComposerMentions } from '@/hooks/useChatComposerMentions';
import { ComposerMentionPicker } from '@/components/chat/ComposerMentionPicker';
import { useRef } from 'react';

vi.mock('@/api/client', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  unwrapGatewayPayload: <T,>(v: any): T => v,
}));

vi.mock('react-i18next', async () => {
  const actual: any = await vi.importActual('react-i18next');
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string, opts?: any) => (opts?.defaultValue ?? key),
    }),
  };
});

import { api } from '@/api/client';

const RESOURCE_LIST = [
  {
    server_id: 'docs',
    uri: 'file:///readme.md',
    name: 'README',
    mimeType: 'text/markdown',
  },
  {
    server_id: 'docs',
    uri: 'file:///changelog.md',
    name: 'Changelog',
    mimeType: 'text/markdown',
  },
  {
    server_id: 'github',
    uri: 'github://issues',
    name: 'Issues',
  },
];

const RESPONSE = { data: RESOURCE_LIST };

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.get).mockResolvedValue(RESPONSE as any);
});

describe('useChatComposerMentions', () => {
  it('opens the picker when @ is typed at word boundary', async () => {
    const Harness = () => {
      const ref = useRef<HTMLTextAreaElement>(null);
      const hook = useChatComposerMentions({
        inputValue: '',
        setInputValue: () => undefined,
        textareaRef: ref,
        addMcpResourceDraft: () => undefined,
      });
      return (
        <div>
          <textarea ref={ref} />
          <button
            data-testid="type-at"
            onClick={() => {
              if (ref.current) {
                ref.current.value = '@';
                ref.current.setSelectionRange(1, 1);
              }
              hook.onValueChange('@');
            }}
          />
          <div data-testid="open">{String(hook.state.open)}</div>
        </div>
      );
    };
    render(<Harness />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('type-at'));
    });
    expect(screen.getByTestId('open').textContent).toBe('true');
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/mcp/resources'));
  });

  it('does not open for @ in the middle of an email-like token', () => {
    const Harness = () => {
      const ref = useRef<HTMLTextAreaElement>(null);
      const hook = useChatComposerMentions({
        inputValue: 'foo@bar',
        setInputValue: () => undefined,
        textareaRef: ref,
        addMcpResourceDraft: () => undefined,
      });
      return (
        <div>
          <textarea ref={ref} />
          <button
            data-testid="type"
            onClick={() => {
              if (ref.current) {
                ref.current.value = 'foo@bar';
                ref.current.setSelectionRange(7, 7);
              }
              hook.onValueChange('foo@bar');
            }}
          />
          <div data-testid="open">{String(hook.state.open)}</div>
        </div>
      );
    };
    render(<Harness />);
    fireEvent.click(screen.getByTestId('type'));
    expect(screen.getByTestId('open').textContent).toBe('false');
  });

  it('filters items by the @-query', async () => {
    const Harness = () => {
      const ref = useRef<HTMLTextAreaElement>(null);
      const hook = useChatComposerMentions({
        inputValue: '@change',
        setInputValue: () => undefined,
        textareaRef: ref,
        addMcpResourceDraft: () => undefined,
      });
      return (
        <div>
          <textarea ref={ref} />
          <button
            data-testid="type"
            onClick={() => {
              if (ref.current) {
                ref.current.value = '@change';
                ref.current.setSelectionRange(7, 7);
              }
              hook.onValueChange('@change');
            }}
          />
          <ul data-testid="items">
            {hook.items.map((it) => (
              <li key={it.uri}>{it.name}</li>
            ))}
          </ul>
        </div>
      );
    };
    render(<Harness />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('type'));
    });
    await waitFor(() => {
      const list = screen.getByTestId('items');
      expect(list.textContent).toContain('Changelog');
      expect(list.textContent).not.toContain('Issues');
    });
  });

  it('select() strips @-query token from the textarea and adds a draft', async () => {
    const drafts: any[] = [];
    let inputState = 'hello @read';
    const setInputState = vi.fn((v: string) => {
      inputState = v;
    });

    const Harness = () => {
      const ref = useRef<HTMLTextAreaElement>(null);
      const hook = useChatComposerMentions({
        inputValue: inputState,
        setInputValue: setInputState,
        textareaRef: ref,
        addMcpResourceDraft: (r) => drafts.push(r),
      });

      return (
        <div>
          <textarea ref={ref} defaultValue={inputState} />
          <button
            data-testid="open"
            onClick={() => {
              if (ref.current) {
                ref.current.setSelectionRange(11, 11);
              }
              hook.onValueChange(inputState);
            }}
          />
          <button
            data-testid="select-first"
            onClick={() => {
              const first = hook.items[0];
              if (first) hook.select(first);
            }}
          />
        </div>
      );
    };

    render(<Harness />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('open'));
    });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    await act(async () => {
      fireEvent.click(screen.getByTestId('select-first'));
    });
    expect(drafts).toHaveLength(1);
    expect(drafts[0]).toMatchObject({ serverId: 'docs', uri: 'file:///readme.md' });
    expect(setInputState).toHaveBeenLastCalledWith('hello');
  });
});

describe('ComposerMentionPicker', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <ComposerMentionPicker
        open={false}
        query=""
        items={[]}
        activeIndex={0}
        loading={false}
        error={null}
        onSelect={() => undefined}
        onActiveIndexChange={() => undefined}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('shows empty state when no items', () => {
    render(
      <ComposerMentionPicker
        open
        query=""
        items={[]}
        activeIndex={0}
        loading={false}
        error={null}
        onSelect={() => undefined}
        onActiveIndexChange={() => undefined}
      />,
    );
    expect(screen.getByText('chat.mentions.empty')).toBeTruthy();
  });

  it('selects on mouse down', async () => {
    const onSelect = vi.fn();
    render(
      <ComposerMentionPicker
        open
        query=""
        items={[
          { serverId: 'a', uri: 'u', name: 'one' },
          { serverId: 'a', uri: 'u2', name: 'two' },
        ]}
        activeIndex={0}
        loading={false}
        error={null}
        onSelect={onSelect}
        onActiveIndexChange={() => undefined}
      />,
    );
    fireEvent.mouseDown(screen.getByText('two'));
    expect(onSelect).toHaveBeenCalledWith({ serverId: 'a', uri: 'u2', name: 'two' });
  });
});
