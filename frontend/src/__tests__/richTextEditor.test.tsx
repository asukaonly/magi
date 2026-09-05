import { act, render, waitFor } from '@testing-library/react';
import type { Editor } from '@tiptap/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { RichTextEditor } from '@/components/timeline/manual-entries/RichTextEditor';

const state = vi.hoisted(() => ({ editor: null as Editor | null }));
vi.mock('@tiptap/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tiptap/react')>();
  return {
    ...actual,
    useEditor: (...args: Parameters<typeof actual.useEditor>) => {
      state.editor = actual.useEditor(...args);
      return state.editor;
    },
  };
});
beforeEach(() => { state.editor = null; });

it('refreshes the translated placeholder while retaining the editor, draft and undo history', async () => {
  const props = { value: null, onChange: vi.fn(), onChangeText: vi.fn() };
  const { container, rerender, unmount } = render(<RichTextEditor {...props} placeholder="Write a note" />);
  await waitFor(() => expect(container.querySelector('[data-placeholder]')).toHaveAttribute('data-placeholder', 'Write a note'));
  const editor = state.editor!;
  rerender(<RichTextEditor {...props} placeholder="记录一下" />);
  await waitFor(() => expect(container.querySelector('[data-placeholder]')).toHaveAttribute('data-placeholder', '记录一下'));
  act(() => { editor.commands.insertContent('Unsaved draft'); });
  rerender(<RichTextEditor {...props} placeholder="Write again" />);
  expect(state.editor).toBe(editor);
  expect(editor.getText()).toBe('Unsaved draft');
  act(() => { editor.commands.undo(); });
  expect(editor.getText()).toBe('');
  expect(container.querySelector('[data-placeholder]')).toHaveAttribute('data-placeholder', 'Write again');
  unmount();
  await waitFor(() => expect(editor.isDestroyed).toBe(true));
});
