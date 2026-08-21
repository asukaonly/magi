/**
 * Tiptap-based rich text editor for manual memory entries (Phase B-2).
 *
 * Responsibilities:
 *   - Render the editing surface with our shared extension set.
 *   - Expose the current doc as ProseMirror JSON via `onChange`, and
 *     the plain-text projection via `onChangeText`. The parent passes
 *     both to the backend (body_doc + body) on save.
 *   - Show a contextual toolbar on focus — out of the way when typing,
 *     reachable when you want to format.
 *   - Forward image-paste events to the parent so the existing upload
 *     flow keeps working (we treat images as attachments, not inline
 *     nodes — see richTextExtensions.ts for the reasoning).
 *   - Forward Cmd/Ctrl+Enter so the parent can trigger save without
 *     leaving the editor.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import { useTranslation } from 'react-i18next';
import {
  Bold,
  Italic,
  Strikethrough,
  Code,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  Quote,
  Minus,
  Link as LinkIcon,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  buildRichTextExtensions,
  emptyDoc,
  docFromPlainText,
} from './richTextExtensions';

interface RichTextEditorProps {
  /** Current ProseMirror JSON. Null/undefined → seed an empty doc. */
  value: Record<string, unknown> | null | undefined;
  /** Fallback plain text — used to seed the doc when `value` is null
   *  (e.g. editing a pre-rich-text entry). Ignored when `value` is set. */
  fallbackPlainText?: string;
  onChange: (doc: Record<string, unknown>) => void;
  onChangeText: (plainText: string) => void;
  /** Fires for image clipboard items so the parent can upload them via
   *  the existing attachment pipeline. The editor itself won't insert
   *  image nodes — those would conflict with the chip grid above. */
  onPasteImages?: (files: File[]) => void;
  /** Cmd/Ctrl+Enter shortcut — parent decides what to do (typically
   *  triggers save). Returning true blocks Tiptap's default. */
  onSubmitShortcut?: () => void;
  placeholder?: string;
  autoFocus?: boolean;
  /** Minimum editor height in pixels. Defaults to 96 (the historical
   *  quick-capture size). Long-form callers should pass a larger value
   *  so the writing surface doesn't feel like a comment box. */
  minHeightPx?: number;
}

export const RichTextEditor: React.FC<RichTextEditorProps> = ({
  value,
  fallbackPlainText,
  onChange,
  onChangeText,
  onPasteImages,
  onSubmitShortcut,
  placeholder,
  autoFocus,
  minHeightPx = 96,
}) => {
  // Stable initial content: prefer the saved doc, then the plain-text
  // fallback wrapped in a single paragraph, then an empty doc.
  const initialContent = useMemo(() => {
    if (value && Object.keys(value).length > 0) return value;
    if (fallbackPlainText && fallbackPlainText.length > 0) {
      return docFromPlainText(fallbackPlainText);
    }
    return emptyDoc();
    // Intentionally only on mount — runtime value changes flow through
    // editor commands, not via reseeding (which would reset cursor).
  }, []);

  // Build extensions once per mount, capturing the placeholder text.
  // Rebuilding on every render would force Tiptap to re-init the
  // schema and lose the editor's transaction history.
  const extensions = useMemo(
    () => buildRichTextExtensions(placeholder),
    [],
  );

  const editor = useEditor({
    extensions,
    content: initialContent,
    autofocus: autoFocus ?? false,
    editorProps: {
      attributes: {
        // Match the textarea's prior typography so swapping in the editor
        // doesn't reflow the sheet. Tailwind `prose` adds heading/list
        // styles automatically; we scope it tightly to keep the sheet
        // compact.
        class: cn(
          // Custom-styled inside `.rich-text-content` (defined below
          // via <style>) — we don't pull in @tailwindcss/typography
          // for one component. Block styles are defined once and
          // shared between editor + read-only renderer.
          'rich-text-content max-w-none focus:outline-none',
          // Min-height is set via inline style (below) so the long-form
          // caller can override without juggling arbitrary-class values.
          'w-full rounded-md bg-[hsl(var(--app-chrome-surface)/0.58)]',
          'px-3.5 py-3 text-sm leading-6 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.36)]',
          'transition-[box-shadow,background-color] focus-visible:ring-2 focus-visible:ring-primary/20',
        ),
        style: `min-height: ${minHeightPx}px;`,
      },
      // Catch image paste — the editor swallows the event by default;
      // we delegate to the parent's upload flow.
      handlePaste: (_view, event) => {
        const items = event.clipboardData?.items;
        if (!items || items.length === 0) return false;
        const imageFiles: File[] = [];
        for (let i = 0; i < items.length; i++) {
          const it = items[i];
          if (it.kind === 'file' && it.type.startsWith('image/')) {
            const f = it.getAsFile();
            if (f) imageFiles.push(f);
          }
        }
        if (imageFiles.length > 0) {
          event.preventDefault();
          onPasteImages?.(imageFiles);
          return true;
        }
        return false;
      },
      // Cmd/Ctrl+Enter intercept. Return true to mark the key as
      // handled, otherwise Tiptap inserts a newline.
      handleKeyDown: (_view, event) => {
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          onSubmitShortcut?.();
          return true;
        }
        return false;
      },
    },
    onUpdate: ({ editor }) => {
      onChange(editor.getJSON() as Record<string, unknown>);
      onChangeText(editor.getText());
    },
  });

  // Destroy on unmount — useEditor handles this internally but be
  // explicit so we don't leak if the parent re-mounts us.
  useEffect(() => {
    return () => {
      editor?.destroy();
    };
  }, []);

  const applyLink = useCallback(
    (url: string) => {
      if (!editor) return;
      const trimmed = url.trim();
      if (trimmed === '') {
        editor.chain().focus().unsetLink().run();
        return;
      }
      editor
        .chain()
        .focus()
        .extendMarkRange('link')
        .setLink({ href: trimmed })
        .run();
    },
    [editor],
  );

  if (!editor) return null;

  return (
    <div className="space-y-1.5">
      <Toolbar editor={editor} onApplyLink={applyLink} />
      <EditorContent editor={editor} />
      {/* Block typography for .rich-text-content lives in index.css —
          shared with the read-only renderer in DaySceneReader. */}
    </div>
  );
};


/** Single-row icon toolbar. Toolbar buttons mirror the extension set —
 *  see richTextExtensions.ts. Pressed-state is driven off Tiptap's
 *  `isActive(mark | nodeType, attrs?)` which already knows about the
 *  cursor's surrounding context. */
const Toolbar: React.FC<{
  editor: ReturnType<typeof useEditor>;
  onApplyLink: (url: string) => void;
}> = ({ editor, onApplyLink }) => {
  const { t } = useTranslation('app');
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkDraft, setLinkDraft] = useState('');

  // Seed the popover input with the currently-applied URL so editing
  // an existing link is a tweak, not a re-entry.
  const openLinkPopover = useCallback(() => {
    if (!editor) return;
    const current = (editor.getAttributes('link').href as string | undefined) ?? '';
    setLinkDraft(current);
    setLinkOpen(true);
  }, [editor]);

  if (!editor) return null;
  return (
    <div className="flex flex-wrap items-center gap-0.5 rounded-md bg-[hsl(var(--app-chrome-surface)/0.72)] px-1 py-0.5 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.34)]">
      <Btn
        active={editor.isActive('bold')}
        onClick={() => editor.chain().focus().toggleBold().run()}
        title={t('timeline.manualEntry.toolbar.bold', { defaultValue: '粗体 (⌘B)' })}
      >
        <Bold className="h-3.5 w-3.5" />
      </Btn>
      <Btn
        active={editor.isActive('italic')}
        onClick={() => editor.chain().focus().toggleItalic().run()}
        title={t('timeline.manualEntry.toolbar.italic', { defaultValue: '斜体 (⌘I)' })}
      >
        <Italic className="h-3.5 w-3.5" />
      </Btn>
      <Btn
        active={editor.isActive('strike')}
        onClick={() => editor.chain().focus().toggleStrike().run()}
        title={t('timeline.manualEntry.toolbar.strike', { defaultValue: '删除线' })}
      >
        <Strikethrough className="h-3.5 w-3.5" />
      </Btn>
      <Btn
        active={editor.isActive('code')}
        onClick={() => editor.chain().focus().toggleCode().run()}
        title={t('timeline.manualEntry.toolbar.code', { defaultValue: '行内代码' })}
      >
        <Code className="h-3.5 w-3.5" />
      </Btn>
      {/* Link popover — opens an inline input below the button instead
          of window.prompt, which Radix Sheet's focus trap eats. The
          PopoverContent is Portal'd via Radix, so it positions itself
          relative to the trigger and won't clip past the sheet. */}
      <Popover open={linkOpen} onOpenChange={setLinkOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            onClick={openLinkPopover}
            title={t('timeline.manualEntry.toolbar.link', { defaultValue: '链接' })}
            aria-label={t('timeline.manualEntry.toolbar.link', { defaultValue: '链接' })}
            aria-pressed={editor.isActive('link')}
            className={cn(
              'flex h-6 w-6 items-center justify-center rounded-md text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20',
              editor.isActive('link')
                ? 'bg-[hsl(var(--primary)/0.12)] text-foreground'
                : 'text-muted-foreground hover:bg-foreground/5 hover:text-foreground',
            )}
          >
            <LinkIcon className="h-3.5 w-3.5" />
          </button>
        </PopoverTrigger>
        <PopoverContent
          side="bottom"
          align="start"
          sideOffset={6}
          className="flex w-72 items-center gap-1 rounded-lg border-border/40 bg-[hsl(var(--app-chrome-elevated)/0.98)] p-2 shadow-[0_14px_36px_hsl(var(--foreground)/0.12)]"
        >
          <input
            type="url"
            autoFocus
            placeholder="https://…"
            value={linkDraft}
            onChange={(e) => setLinkDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                onApplyLink(linkDraft);
                setLinkOpen(false);
              } else if (e.key === 'Escape') {
                e.preventDefault();
                setLinkOpen(false);
              }
            }}
            className="h-7 flex-1 rounded-md bg-[hsl(var(--app-chrome-surface)/0.72)] px-2 text-xs shadow-[inset_0_0_0_1px_hsl(var(--border)/0.34)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
          />
          <button
            type="button"
            onClick={() => {
              onApplyLink(linkDraft);
              setLinkOpen(false);
            }}
            className="h-7 rounded-md bg-primary px-2.5 text-xs font-semibold text-primary-foreground transition-colors hover:bg-[hsl(var(--primary)/0.92)]"
          >
            {t('timeline.manualEntry.toolbar.applyLink', { defaultValue: '应用' })}
          </button>
          {editor.isActive('link') ? (
            <button
              type="button"
              onClick={() => {
                onApplyLink('');
                setLinkOpen(false);
              }}
              title={t('timeline.manualEntry.toolbar.removeLink', { defaultValue: '移除链接' })}
              className="h-7 rounded-md px-2 text-xs text-muted-foreground transition-colors hover:bg-foreground/5 hover:text-foreground"
            >
              {t('timeline.manualEntry.toolbar.remove', { defaultValue: '移除' })}
            </button>
          ) : null}
        </PopoverContent>
      </Popover>

      <Divider />

      <Btn
        active={editor.isActive('heading', { level: 2 })}
        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
        title={t('timeline.manualEntry.toolbar.heading2', { defaultValue: '二级标题' })}
      >
        <Heading2 className="h-3.5 w-3.5" />
      </Btn>
      <Btn
        active={editor.isActive('heading', { level: 3 })}
        onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
        title={t('timeline.manualEntry.toolbar.heading3', { defaultValue: '三级标题' })}
      >
        <Heading3 className="h-3.5 w-3.5" />
      </Btn>

      <Divider />

      <Btn
        active={editor.isActive('bulletList')}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
        title={t('timeline.manualEntry.toolbar.bulletList', { defaultValue: '无序列表' })}
      >
        <List className="h-3.5 w-3.5" />
      </Btn>
      <Btn
        active={editor.isActive('orderedList')}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
        title={t('timeline.manualEntry.toolbar.orderedList', { defaultValue: '有序列表' })}
      >
        <ListOrdered className="h-3.5 w-3.5" />
      </Btn>
      <Btn
        active={editor.isActive('blockquote')}
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
        title={t('timeline.manualEntry.toolbar.quote', { defaultValue: '引用' })}
      >
        <Quote className="h-3.5 w-3.5" />
      </Btn>
      <Btn
        active={false}
        onClick={() => editor.chain().focus().setHorizontalRule().run()}
        title={t('timeline.manualEntry.toolbar.divider', { defaultValue: '分割线' })}
      >
        <Minus className="h-3.5 w-3.5" />
      </Btn>
    </div>
  );
};

const Btn: React.FC<{
  active: boolean;
  onClick: () => void;
  title: string;
  children: React.ReactNode;
}> = ({ active, onClick, title, children }) => (
  <button
    type="button"
    onClick={onClick}
    title={title}
    aria-label={title}
    aria-pressed={active}
    className={cn(
      'flex h-6 w-6 items-center justify-center rounded-md text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20',
      active
        ? 'bg-[hsl(var(--primary)/0.12)] text-foreground'
        : 'text-muted-foreground hover:bg-foreground/5 hover:text-foreground',
    )}
  >
    {children}
  </button>
);

const Divider: React.FC = () => (
  <span className="mx-0.5 h-4 w-px bg-border/60" aria-hidden="true" />
);
