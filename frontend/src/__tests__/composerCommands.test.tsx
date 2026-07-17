import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, fireEvent, act, within } from '@testing-library/react';
import { useRef } from 'react';
import { useChatComposerCommands } from '@/hooks/useChatComposerCommands';
import { ComposerSlashPicker } from '@/components/chat/ComposerSlashPicker';
import { SkillArgsDialog } from '@/components/chat/SkillArgsDialog';
import { ToolArgsDialog } from '@/components/chat/ToolArgsDialog';

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

const TOOL_LIST = [
  { name: 'echo', description: 'Echo input', category: 'test', dangerous: false, parameters: [{ name: 'text', type: 'string', required: true }] },
  { name: 'rm', description: 'Remove a file', category: 'test', dangerous: true, parameters: [{ name: 'path', type: 'string', required: true }] },
];

const SKILL_LIST = [
  { name: 'pr-review', description: 'Review a pull request', argument_hint: '<pr_number>', tags: [] },
  { name: 'standup', description: 'Daily standup template', tags: [] },
];

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.get).mockImplementation(async (url: string) => {
    if (url === '/commands/') return { data: TOOL_LIST } as any;
    if (url === '/commands/skills') return { data: SKILL_LIST } as any;
    return { data: [] } as any;
  });
  vi.mocked(api.post).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useChatComposerCommands', () => {
  it('opens picker only when / is at message start', async () => {
    const Harness = ({ value, cursor }: { value: string; cursor: number }) => {
      const ref = useRef<HTMLTextAreaElement>(null);
      const hook = useChatComposerCommands({
        setInputValue: () => undefined,
        textareaRef: ref,
        onPickInternal: () => undefined,
        onPickTool: () => undefined,
        onPickSkill: () => undefined,
      });
      return (
        <div>
          <textarea ref={ref} defaultValue={value} />
          <button
            data-testid="trigger"
            onClick={() => {
              if (ref.current) ref.current.setSelectionRange(cursor, cursor);
              hook.onValueChange(value);
            }}
          />
          <div data-testid="open">{String(hook.state.open)}</div>
          <div data-testid="items">{hook.items.length}</div>
        </div>
      );
    };

    const { rerender } = render(<Harness value="/" cursor={1} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('trigger'));
    });
    expect(screen.getByTestId('open').textContent).toBe('true');

    rerender(<Harness value="hello /" cursor={7} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('trigger'));
    });
    expect(screen.getByTestId('open').textContent).toBe('false');
  });

  it('merges internal commands with tool list', async () => {
    const Harness = () => {
      const ref = useRef<HTMLTextAreaElement>(null);
      const hook = useChatComposerCommands({
        setInputValue: () => undefined,
        textareaRef: ref,
        onPickInternal: () => undefined,
        onPickTool: () => undefined,
        onPickSkill: () => undefined,
      });
      return (
        <div>
          <textarea ref={ref} defaultValue="/" />
          <button
            data-testid="open"
            onClick={() => {
              if (ref.current) ref.current.setSelectionRange(1, 1);
              hook.onValueChange('/');
            }}
          />
          <ul data-testid="items">
            {hook.items.map((item) => (
              <li key={`${item.source}|${item.name}`}>{item.source}|{item.name}</li>
            ))}
          </ul>
        </div>
      );
    };
    render(<Harness />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('open'));
    });
    await waitFor(() => {
      const text = screen.getByTestId('items').textContent;
      expect(text).toContain('internal|clear');
      expect(text).toContain('tool|echo');
      expect(text).toContain('tool|rm');
    });
  });

  it('marks the clear command as destructive before selection', async () => {
    const Harness = () => {
      const ref = useRef<HTMLTextAreaElement>(null);
      const hook = useChatComposerCommands({
        setInputValue: () => undefined,
        textareaRef: ref,
        onPickInternal: () => undefined,
        onPickTool: () => undefined,
        onPickSkill: () => undefined,
      });
      return (
        <div>
          <textarea ref={ref} defaultValue="/cl" />
          <button
            data-testid="open"
            onClick={() => {
              if (ref.current) ref.current.setSelectionRange(3, 3);
              hook.onValueChange('/cl');
            }}
          />
          <ComposerSlashPicker
            open={hook.state.open}
            query={hook.state.open ? hook.state.query : ''}
            items={hook.items}
            activeIndex={hook.state.open ? hook.state.activeIndex : 0}
            loading={hook.loading}
            error={hook.error}
            onSelect={hook.select}
            onActiveIndexChange={hook.setActiveIndex}
          />
        </div>
      );
    };

    render(<Harness />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('open'));
    });

    const clearOption = await screen.findByRole('option', { name: /\/clear/ });
    expect(clearOption).toHaveTextContent('Clear this chat and its related memories');
    expect(within(clearOption).getByLabelText('chat.commands.dangerous')).toBeInTheDocument();
  });

  it('select on internal command runs handler and clears input', async () => {
    const setInputValue = vi.fn();
    const onPickInternal = vi.fn();
    const Harness = () => {
      const ref = useRef<HTMLTextAreaElement>(null);
      const hook = useChatComposerCommands({
        setInputValue,
        textareaRef: ref,
        onPickInternal,
        onPickTool: () => undefined,
        onPickSkill: () => undefined,
      });
      return (
        <div>
          <textarea ref={ref} defaultValue="/cl" />
          <button
            data-testid="open"
            onClick={() => {
              if (ref.current) ref.current.setSelectionRange(3, 3);
              hook.onValueChange('/cl');
            }}
          />
          <button
            data-testid="select-clear"
            onClick={() => {
              const item = hook.items.find((i) => i.source === 'internal' && i.name === 'clear');
              if (item) hook.select(item);
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
      fireEvent.click(screen.getByTestId('select-clear'));
    });
    expect(setInputValue).toHaveBeenCalledWith('');
    expect(onPickInternal).toHaveBeenCalledWith('clear');
  });

  it('select on tool command opens dialog via onPickTool', async () => {
    const onPickTool = vi.fn();
    const Harness = () => {
      const ref = useRef<HTMLTextAreaElement>(null);
      const hook = useChatComposerCommands({
        setInputValue: () => undefined,
        textareaRef: ref,
        onPickInternal: () => undefined,
        onPickTool,
        onPickSkill: () => undefined,
      });
      return (
        <div>
          <textarea ref={ref} defaultValue="/echo" />
          <button
            data-testid="open"
            onClick={() => {
              if (ref.current) ref.current.setSelectionRange(5, 5);
              hook.onValueChange('/echo');
            }}
          />
          <button
            data-testid="select-echo"
            onClick={() => {
              const item = hook.items.find((i) => i.source === 'tool' && i.name === 'echo');
              if (item) hook.select(item);
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
      fireEvent.click(screen.getByTestId('select-echo'));
    });
    expect(onPickTool).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'echo' }),
    );
  });

  it('select on skill command invokes onPickSkill', async () => {
    const onPickSkill = vi.fn();
    const Harness = () => {
      const ref = useRef<HTMLTextAreaElement>(null);
      const hook = useChatComposerCommands({
        setInputValue: () => undefined,
        textareaRef: ref,
        onPickInternal: () => undefined,
        onPickTool: () => undefined,
        onPickSkill,
      });
      return (
        <div>
          <textarea ref={ref} defaultValue="/pr" />
          <button
            data-testid="open"
            onClick={() => {
              if (ref.current) ref.current.setSelectionRange(3, 3);
              hook.onValueChange('/pr');
            }}
          />
          <button
            data-testid="select-skill"
            onClick={() => {
              const item = hook.items.find(
                (i) => i.source === 'skill' && i.name === 'pr-review',
              );
              if (item) hook.select(item);
            }}
          />
        </div>
      );
    };
    render(<Harness />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('open'));
    });
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/commands/skills'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('select-skill'));
    });
    expect(onPickSkill).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'pr-review' }),
    );
  });
});

describe('ComposerSlashPicker', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <ComposerSlashPicker
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

  it('renders internal vs tool items differently', () => {
    render(
      <ComposerSlashPicker
        open
        query=""
        items={[
          { source: 'internal', name: 'clear', description: 'clear', action: 'clear' },
          {
            source: 'tool',
            name: 'echo',
            description: 'echo',
            dangerous: false,
            descriptor: { name: 'echo', description: 'echo', category: 'test', dangerous: false, parameters: [] },
          },
        ]}
        activeIndex={0}
        loading={false}
        error={null}
        onSelect={() => undefined}
        onActiveIndexChange={() => undefined}
      />,
    );
    expect(screen.getByText('/clear')).toBeTruthy();
    expect(screen.getByText('/echo')).toBeTruthy();
  });
});

describe('ToolArgsDialog', () => {
  it('renders form with required marker for required parameters', () => {
    render(
      <ToolArgsDialog
        open
        descriptor={{
          name: 'echo',
          description: 'Echo input',
          category: 'test',
          dangerous: false,
          parameters: [
            { name: 'text', type: 'string', required: true, description: 'the message' },
          ],
        }}
        onClose={() => undefined}
        onRun={async () => undefined}
      />,
    );
    expect(screen.getByText('text')).toBeTruthy();
    expect(screen.getByText('(string)')).toBeTruthy();
    expect(screen.getByText('the message')).toBeTruthy();
  });

  it('blocks submit when required field missing', async () => {
    const onRun = vi.fn(async () => undefined);
    render(
      <ToolArgsDialog
        open
        descriptor={{
          name: 'echo',
          description: '',
          category: 'test',
          dangerous: false,
          parameters: [{ name: 'text', type: 'string', required: true }],
        }}
        onClose={() => undefined}
        onRun={onRun}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    expect(onRun).not.toHaveBeenCalled();
  });

  it('runs with coerced args when valid', async () => {
    const onRun = vi.fn(async () => undefined);
    const onClose = vi.fn();
    render(
      <ToolArgsDialog
        open
        descriptor={{
          name: 'echo',
          description: '',
          category: 'test',
          dangerous: false,
          parameters: [
            { name: 'text', type: 'string', required: true },
            { name: 'count', type: 'integer' },
          ],
        }}
        onClose={onClose}
        onRun={onRun}
      />,
    );
    const inputs = screen.getAllByRole('textbox');
    fireEvent.change(inputs[0], { target: { value: 'hi' } });
    const numberInputs = document.querySelectorAll('input[type="number"]');
    fireEvent.change(numberInputs[0], { target: { value: '3' } });
    fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    await waitFor(() => expect(onRun).toHaveBeenCalled());
    const [, args, invText] = onRun.mock.calls[0] as unknown as [unknown, Record<string, unknown>, string];
    expect(args).toEqual({ text: 'hi', count: 3 });
    expect(invText).toBe('/echo text=hi count=3');
  });

  it('shows dangerous notice', () => {
    render(
      <ToolArgsDialog
        open
        descriptor={{
          name: 'rm',
          description: 'remove',
          category: 'test',
          dangerous: true,
          parameters: [],
        }}
        onClose={() => undefined}
        onRun={async () => undefined}
      />,
    );
    expect(screen.getByText(/dangerous tool/i)).toBeTruthy();
  });
  it('renders fork badge for skills with context_mode=fork', () => {
    render(
      <ComposerSlashPicker
        open
        query=""
        items={[
          {
            source: 'skill',
            name: 'deep-scan',
            description: 'Audit',
            argumentHint: undefined,
            contextMode: 'fork',
            descriptor: {
              name: 'deep-scan',
              description: 'Audit',
              tags: [],
              context_mode: 'fork',
            },
          },
        ]}
        activeIndex={0}
        loading={false}
        error={null}
        onSelect={() => undefined}
        onActiveIndexChange={() => undefined}
      />,
    );
    expect(screen.getByText('fork')).toBeTruthy();
  });
});

describe('SkillArgsDialog', () => {
  it('renders argument hint and forwards args text on submit', async () => {
    const onSubmit = vi.fn(async () => undefined);
    render(
      <SkillArgsDialog
        open
        descriptor={{
          name: 'pr-review',
          description: 'Review a pull request',
          argument_hint: '<pr_number>',
          tags: [],
        }}
        onClose={() => undefined}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByText(/pr-review/)).toBeTruthy();
    expect(screen.getByText('<pr_number>')).toBeTruthy();
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: '123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const [desc, argsText] = onSubmit.mock.calls[0] as unknown as [{ name: string }, string];
    expect(desc.name).toBe('pr-review');
    expect(argsText).toBe('123');
  });

  it('Enter key submits the dialog', async () => {
    const onSubmit = vi.fn(async () => undefined);
    render(
      <SkillArgsDialog
        open
        descriptor={{
          name: 'pr-review',
          description: '',
          argument_hint: '<pr>',
          tags: [],
        }}
        onClose={() => undefined}
        onSubmit={onSubmit}
      />,
    );
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: '99' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
  });

  it('shows fork notice when descriptor.context_mode is fork', () => {
    render(
      <SkillArgsDialog
        open
        descriptor={{
          name: 'deep-scan',
          description: 'Audit',
          argument_hint: '<glob>',
          tags: [],
          context_mode: 'fork',
        }}
        onClose={() => undefined}
        onSubmit={async () => undefined}
      />,
    );
    expect(screen.getByText(/background task/i)).toBeTruthy();
  });
});
