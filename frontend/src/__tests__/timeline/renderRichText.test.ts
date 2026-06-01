/**
 * renderRichTextHtml: ProseMirror JSON → HTML conversion. Pure-function
 * coverage (no Tiptap-in-jsdom contenteditable shenanigans), focused on
 * the contract that downstream consumers care about:
 *
 *   - Common marks/nodes produce sensible HTML tags.
 *   - body_doc=null falls back to the plain-text body.
 *   - Malformed body_doc doesn't throw — we degrade to plain text.
 */
import { describe, it, expect } from "vitest";

import { renderRichTextHtml } from "@/components/timeline/manual-entries/renderRichText";

describe("renderRichTextHtml", () => {
  it("renders a bold mark as <strong>", () => {
    const doc = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", text: "今天" },
            { type: "text", marks: [{ type: "bold" }], text: "真好" },
          ],
        },
      ],
    };
    const html = renderRichTextHtml(doc, "今天真好");
    expect(html).toContain("<strong>真好</strong>");
    expect(html).toContain("今天");
  });

  it("renders headings at the expected levels", () => {
    const doc = {
      type: "doc",
      content: [
        { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "标题" }] },
        { type: "heading", attrs: { level: 3 }, content: [{ type: "text", text: "次级" }] },
      ],
    };
    const html = renderRichTextHtml(doc, "");
    expect(html).toMatch(/<h2[^>]*>\s*标题\s*<\/h2>/);
    expect(html).toMatch(/<h3[^>]*>\s*次级\s*<\/h3>/);
  });

  it("renders bullet lists and blockquotes", () => {
    const doc = {
      type: "doc",
      content: [
        {
          type: "bulletList",
          content: [
            { type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "a" }] }] },
            { type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "b" }] }] },
          ],
        },
        {
          type: "blockquote",
          content: [{ type: "paragraph", content: [{ type: "text", text: "引用" }] }],
        },
      ],
    };
    const html = renderRichTextHtml(doc, "");
    expect(html).toContain("<ul>");
    expect(html).toContain("<li>");
    expect(html).toContain("<blockquote>");
  });

  it("falls back to plain text when body_doc is null", () => {
    const html = renderRichTextHtml(null, "纯文本回忆");
    expect(html).toContain("纯文本回忆");
    // Wrapped in a paragraph by docFromPlainText
    expect(html).toMatch(/<p>\s*纯文本回忆\s*<\/p>/);
  });

  it("falls back to plain text when body_doc is an empty object", () => {
    const html = renderRichTextHtml({}, "fallback");
    expect(html).toContain("fallback");
  });

  it("degrades to plain text rather than throwing on a malformed doc", () => {
    // `{type: 'unknown_node'}` isn't a node Tiptap knows about. The
    // renderer catches the error and renders the plain-text fallback.
    const html = renderRichTextHtml({ type: "doc", content: [{ type: "not_a_real_node" }] }, "rescue");
    expect(html).toContain("rescue");
  });
});
