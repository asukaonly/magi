import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { mergeAttributes } from '@tiptap/core';
import type { Editor } from '@tiptap/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { RichTextEditor } from '@/components/timeline/manual-entries/RichTextEditor';
import { renderRichTextHtml } from '@/components/timeline/manual-entries/renderRichText';

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

it('updates toolbar state after document and selection transactions', async () => {
  render(<RichTextEditor value={null} onChange={vi.fn()} onChangeText={vi.fn()} />);
  await waitFor(() => expect(state.editor).not.toBeNull());
  const editor = state.editor!;
  act(() => {
    editor.commands.insertContent('Draft');
    editor.commands.setTextSelection({ from: 1, to: 6 });
    editor.commands.toggleBold();
  });
  expect(screen.getByRole('button', { name: '粗体 (⌘B)' })).toHaveAttribute('aria-pressed', 'true');
  act(() => { editor.commands.toggleBold(); });
  expect(screen.getByRole('button', { name: '粗体 (⌘B)' })).toHaveAttribute('aria-pressed', 'false');
  act(() => { editor.commands.toggleHeading({ level: 2 }); });
  expect(screen.getByRole('button', { name: '二级标题' })).toHaveAttribute('aria-pressed', 'true');
});

it('refreshes every empty block without changing document or selection', async () => {
  const value = { type: 'doc', content: [{ type: 'paragraph' }, { type: 'paragraph' }] };
  const props = { value, onChange: vi.fn(), onChangeText: vi.fn() };
  const { container, rerender } = render(<RichTextEditor {...props} placeholder="Write" />);
  await waitFor(() => expect(container.querySelectorAll('[data-placeholder]')).toHaveLength(2));
  const editor = state.editor!;
  const document = editor.getJSON();
  const selection = editor.state.selection.toJSON();
  rerender(<RichTextEditor {...props} placeholder="记录" />);
  for (const block of container.querySelectorAll('[data-placeholder]')) {
    expect(block).toHaveAttribute('data-placeholder', '记录');
  }
  expect(editor.getJSON()).toEqual(document);
  expect(editor.state.selection.toJSON()).toEqual(selection);
  expect(props.onChange).not.toHaveBeenCalled();
});

it('preserves saved rich text and renders subsequent edits', async () => {
  const value = {
    type: 'doc',
    content: [
      { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'Title' }] },
      { type: 'paragraph', content: [{ type: 'text', text: 'Read', marks: [{ type: 'link', attrs: { href: 'https://example.com' } }, { type: 'bold' }] }] },
      { type: 'bulletList', content: [{ type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Item' }] }] }] },
    ],
  };
  const onChange = vi.fn();
  render(<RichTextEditor value={value} onChange={onChange} onChangeText={vi.fn()} />);
  await waitFor(() => expect(state.editor).not.toBeNull());
  const editor = state.editor!;
  expect(editor.extensionManager.extensions.filter(extension => extension.name === 'link')).toHaveLength(1);
  expect(editor.schema.marks).not.toHaveProperty('underline');
  act(() => { editor.commands.insertContentAt(1, 'Edited '); });
  const saved = onChange.mock.lastCall![0];
  const html = renderRichTextHtml(saved, '');
  expect(html).toContain('<h2>Edited Title</h2>');
  expect(html).toContain('href="https://example.com"');
  expect(html).toContain('<strong>Read</strong>');
  expect(html).toContain('<ul><li><p>Item</p></li></ul>');
});

it('rejects inherited executable attributes and escapes fallback text', () => {
  const attributes = JSON.parse('{"__proto__":{"onerror":"alert(1)","data-inherited-canary":"present"}}');
  const merged = mergeAttributes(attributes);
  expect(merged.onerror).toBeUndefined();
  expect(merged['data-inherited-canary']).toBeUndefined();
  const document = JSON.parse('{"type":"doc","content":[{"type":"paragraph","attrs":{"__proto__":{"onclick":"alert(1)"}},"content":[{"type":"text","text":"Safe","marks":[{"type":"link","attrs":{"href":"javascript:alert(1)","__proto__":{"onerror":"alert(1)"}}}]}]}]}');
  const html = renderRichTextHtml(document, '');
  expect(html).not.toMatch(/javascript:|onclick=|onerror=/i);
  expect(html).toContain('Safe');
  expect(renderRichTextHtml({ type: 'unsupported-node' }, '<script>alert(1)</script>')).toContain('&lt;script&gt;');
});

it('delegates pasted images and the submit shortcut without adding inline images', async () => {
  const onPasteImages = vi.fn();
  const onSubmitShortcut = vi.fn();
  const { container } = render(<RichTextEditor value={null} onChange={vi.fn()} onChangeText={vi.fn()} onPasteImages={onPasteImages} onSubmitShortcut={onSubmitShortcut} />);
  await waitFor(() => expect(state.editor).not.toBeNull());
  const input = container.querySelector('.tiptap')!;
  const image = new File(['image'], 'photo.png', { type: 'image/png' });
  fireEvent.paste(input, { clipboardData: { getData: () => '', items: [{ kind: 'file', type: 'image/png', getAsFile: () => image }] } });
  fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true });
  expect(onPasteImages).toHaveBeenCalledWith([image]);
  expect(onSubmitShortcut).toHaveBeenCalledOnce();
  expect(state.editor!.getText()).toBe('');
  expect(container.querySelector('.tiptap img')).toBeNull();
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
