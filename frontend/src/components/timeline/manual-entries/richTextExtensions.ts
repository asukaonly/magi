/**
 * Single source of truth for the Tiptap extension list. Both the editing
 * surface (`RichTextEditor`) and the read-only renderer (`renderRichText`)
 * import this so the schema can't drift between write and read.
 *
 * Scope (Phase B-2, "medium"):
 *   - Inline marks: bold, italic, strikethrough, inline code, link
 *   - Block: paragraph, H2/H3 (no H1 — entries aren't documents-with-titles),
 *     bullet list, ordered list, blockquote, horizontal rule, hard break
 *
 * Notably excluded:
 *   - CodeBlock — inline `code` mark is enough for diary use
 *   - Images — kept as a separate `attachments[]` array; inlining is a
 *     UX rabbit hole (drag handles, captions, alignment) and the
 *     existing thumbnail grid handles images well
 *   - Tables / task lists / typography enhancements — out of scope
 */

import StarterKit from '@tiptap/starter-kit';
import Link from '@tiptap/extension-link';
import Placeholder from '@tiptap/extension-placeholder';

/** Build the extension list. ``placeholder`` is a parameter (not baked
 *  into a constant) so the editor and the read-only renderer can share
 *  the rest of the schema while differing only on the cue text. The
 *  renderer passes an empty string so the placeholder rule is a no-op
 *  at display time. */
export function buildRichTextExtensions(placeholder = '') {
  return [
    StarterKit.configure({
      // Limit headings to H2/H3 — H1 would visually compete with the
      // entry's own time/place chrome in the timeline view.
      heading: { levels: [2, 3] },
      // Drop the code-block node (block fenced code). The inline `code`
      // mark from StarterKit covers the "monospace fragment" case which
      // is the only one diary entries actually need.
      codeBlock: false,
    }),
    // openOnClick:false avoids triggering navigation when the user
    // clicks a link while editing — surprising and easy to do by
    // accident.
    Link.configure({
      openOnClick: false,
      HTMLAttributes: {
        class: 'underline underline-offset-2 text-primary hover:opacity-80',
        target: '_blank',
        rel: 'noopener noreferrer',
      },
    }),
    Placeholder.configure({
      placeholder,
      // Show the placeholder on every empty block so converting to a
      // heading mid-write doesn't make the cue vanish.
      showOnlyWhenEditable: true,
      showOnlyCurrent: false,
    }),
  ];
}

/** Pre-built extension list with an empty placeholder. Use this when
 *  the caller (read-only renderer) doesn't need a cue. */
export const richTextExtensions = buildRichTextExtensions();

/**
 * Empty doc — used to seed a fresh editor when no body_doc exists. Kept
 * as a function (not a constant) because Tiptap mutates the doc on edit
 * and reusing the same reference across mounts can produce stale state.
 */
export function emptyDoc(): Record<string, unknown> {
  return {
    type: 'doc',
    content: [{ type: 'paragraph' }],
  };
}

/**
 * Wrap a plain string as a single-paragraph doc — used to upgrade
 * pre-rich-text entries on read so the renderer doesn't have a
 * special-case path.
 */
export function docFromPlainText(text: string): Record<string, unknown> {
  return {
    type: 'doc',
    content: [
      {
        type: 'paragraph',
        content: text ? [{ type: 'text', text }] : [],
      },
    ],
  };
}
