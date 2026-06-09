import type { Components } from 'react-markdown';

import { openExternalUrl } from '@/runtime/desktop';
import { CodeBlock } from './code-block';

/**
 * Shared react-markdown component map used by every markdown surface in the app.
 *
 * - ``comfortable`` — the main chat transcript bubble: larger type scale
 *   (``text-sm leading-7``) tuned for Chinese prose readability.
 * - ``compact`` — secondary surfaces (cards, drawers, status panels): tighter
 *   spacing and a smaller code scale.
 *
 * Fenced code blocks render through {@link CodeBlock} — a light panel with a
 * thin header (language label + copy button) — instead of the chat bubble's old
 * inverted dark/terminal block. Inline code stays a small light pill.
 */
export type MarkdownDensity = 'comfortable' | 'compact';

// ---- fenced-code extraction -------------------------------------------------

function normalizeClassList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(String);
  }
  if (typeof value === 'string') {
    return value.split(/\s+/).filter(Boolean);
  }
  return [];
}

function collectText(node: unknown): string {
  if (!node || typeof node !== 'object') {
    return '';
  }
  const n = node as { type?: string; value?: string; children?: unknown[] };
  if (n.type === 'text' && typeof n.value === 'string') {
    return n.value;
  }
  if (Array.isArray(n.children)) {
    return n.children.map(collectText).join('');
  }
  return '';
}

// react-markdown hands the ``pre`` renderer the hast node for the fence; the raw
// text and language live on its child ``code`` element. Reading them from the
// node (rather than from rendered children) means single-line, no-language
// fences are still treated as blocks — and lets CodeBlock own the panel.
function extractFencedCode(node: unknown): { code: string; language?: string } {
  const root = node as { children?: unknown[] } | undefined;
  const codeEl = root?.children?.find((child) => {
    const c = child as { type?: string; tagName?: string };
    return c?.type === 'element' && c?.tagName === 'code';
  }) as { properties?: { className?: unknown }; children?: unknown[] } | undefined;
  const language = normalizeClassList(codeEl?.properties?.className)
    .map((cls) => /^language-(.+)$/.exec(cls)?.[1])
    .find((lang): lang is string => Boolean(lang));
  const code = collectText({ children: codeEl?.children }).replace(/\n$/, '');
  return { code, language };
}

// ---- component maps ---------------------------------------------------------

// Elements whose styling is identical across surfaces — defined once.
const structuralComponents: Components = {
  h1: ({ children }) => (
    <h1 className="mb-4 mt-1 border-b border-border/60 pb-2 text-xl font-semibold tracking-[-0.03em] text-foreground">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-3 mt-6 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => <h3 className="mb-2 mt-4 text-base font-semibold leading-snug text-foreground">{children}</h3>,
  li: ({ children }) => <li className="pl-1">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  blockquote: ({ children }) => (
    <blockquote className="mb-3 rounded-r-2xl border-l-4 border-primary/35 bg-primary/5 px-4 py-3 text-sm leading-7 text-foreground/85 shadow-sm">
      {children}
    </blockquote>
  ),
  table: ({ children }) => (
    <div className="mb-3 overflow-x-auto rounded-2xl border border-border/60 bg-background/80 shadow-sm">
      <table className="min-w-full border-collapse text-sm leading-6 text-foreground">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted/60 text-left text-xs uppercase tracking-[0.16em] text-muted-foreground">{children}</thead>,
  tbody: ({ children }) => <tbody className="divide-y divide-border/50">{children}</tbody>,
  tr: ({ children }) => <tr className="align-top">{children}</tr>,
  th: ({ children }) => <th className="px-3 py-2 font-semibold">{children}</th>,
  td: ({ children }) => <td className="px-3 py-2.5 text-sm text-foreground/90">{children}</td>,
  hr: () => <hr className="my-5 border-border/60" />,
  a: ({ href, children }) => (
    <a
      href={href}
      className="font-medium text-primary underline decoration-primary/45 underline-offset-4 transition-colors hover:text-primary/80"
      target="_blank"
      rel="noreferrer"
      onClick={(event) => {
        if (!href) {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        void openExternalUrl(href);
      }}
    >
      {children}
    </a>
  ),
};

// Text-flow elements whose type scale / spacing differ per density. Fenced
// blocks are rendered by ``pre`` (via CodeBlock) reading the hast node, so the
// ``code`` renderer below only ever styles genuine inline code.
const comfortableTextComponents: Components = {
  p: ({ children }) => <p className="mb-3 whitespace-pre-wrap text-sm leading-7 text-foreground last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-3 list-disc space-y-2 pl-5 text-sm leading-7 text-foreground marker:text-muted-foreground">{children}</ul>,
  ol: ({ children, start }) => <ol start={start} className="mb-3 list-decimal space-y-2 pl-5 text-sm leading-7 text-foreground marker:text-muted-foreground">{children}</ol>,
  code: ({ children }) => (
    <code className="rounded-md border border-border/60 bg-background/90 px-1.5 py-0.5 font-mono text-[0.84em] text-foreground shadow-sm">
      {children}
    </code>
  ),
  pre: ({ node }) => {
    const { code, language } = extractFencedCode(node);
    return <CodeBlock code={code} language={language} density="comfortable" />;
  },
};

const compactTextComponents: Components = {
  p: ({ children }) => <p className="m-0 whitespace-pre-wrap leading-6 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-1 list-disc space-y-1 pl-5 leading-6 marker:text-muted-foreground">{children}</ul>,
  ol: ({ children, start }) => <ol start={start} className="my-1 list-decimal space-y-1 pl-5 leading-6 marker:text-muted-foreground">{children}</ol>,
  code: ({ children }) => (
    <code className="rounded border border-border/60 bg-muted/60 px-1 py-0.5 font-mono text-[0.9em] text-foreground">
      {children}
    </code>
  ),
  pre: ({ node }) => {
    const { code, language } = extractFencedCode(node);
    return <CodeBlock code={code} language={language} density="compact" />;
  },
};

export function createMarkdownComponents(density: MarkdownDensity = 'comfortable'): Components {
  return {
    ...structuralComponents,
    ...(density === 'compact' ? compactTextComponents : comfortableTextComponents),
  };
}
