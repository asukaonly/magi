/**
 * Pure-function ProseMirror-JSON → HTML conversion for display in
 * places we don't want to spin up a full editor instance (e.g. the
 * timeline's ManualEntryRow, which renders many entries at once).
 *
 * The HTML output uses the same extension list as the editor, so what
 * the user typed is what they see — there's no separate "view schema"
 * that could silently drop a mark.
 *
 * Falls back to wrapping plain text in a paragraph when no body_doc
 * was stored (entries created before Phase B-2).
 */

import { generateHTML } from '@tiptap/html';

import { richTextExtensions, docFromPlainText } from './richTextExtensions';

export function renderRichTextHtml(
  bodyDoc: Record<string, unknown> | null | undefined,
  fallbackPlainText: string,
): string {
  if (bodyDoc && Object.keys(bodyDoc).length > 0) {
    try {
      return generateHTML(bodyDoc as never, richTextExtensions);
    } catch {
      // Malformed doc — fall through to plain text so the row still
      // renders something (better degradation than a crash).
    }
  }
  // No doc → wrap the plain string in a single paragraph node so we
  // get consistent whitespace/wrapping behavior across rich and
  // legacy entries.
  return generateHTML(
    docFromPlainText(fallbackPlainText) as never,
    richTextExtensions,
  );
}
