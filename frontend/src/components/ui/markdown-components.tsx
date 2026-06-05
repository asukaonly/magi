import type { Components } from 'react-markdown';

import { openExternalUrl } from '@/runtime/desktop';

/**
 * Shared react-markdown component map used by every markdown surface in the app.
 *
 * - ``comfortable`` — the main chat transcript bubble: larger type scale
 *   (``text-sm leading-7``) tuned for Chinese prose readability.
 * - ``compact`` — secondary surfaces (cards, drawers, status panels): tighter
 *   spacing and a smaller code scale.
 *
 * Code blocks render as a soft light panel (``bg-muted/50``) on both densities
 * so they stay consistent with the surrounding UI instead of inverting to a
 * dark terminal block.
 */
export type MarkdownDensity = 'comfortable' | 'compact';

// Build a fenced/inline code renderer. ``react-markdown`` uses the same ``code``
// element for both; a fenced block carries a language ``className`` (or spans
// multiple lines), in which case it sits inside a styled ``pre`` and only needs
// to inherit the monospace scale — the visible panel comes from ``pre``.
function makeCodeComponent(blockClassName: string, inlineClassName: string): Components['code'] {
  return ({ className, children }) => {
    const content = String(children ?? '').replace(/\n$/, '');
    const isBlockCode = Boolean(className) || content.includes('\n');
    if (isBlockCode) {
      return <code className={blockClassName}>{children}</code>;
    }
    return <code className={inlineClassName}>{children}</code>;
  };
}

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

// Text-flow elements whose type scale / spacing differ per density.
const comfortableTextComponents: Components = {
  p: ({ children }) => <p className="mb-3 whitespace-pre-wrap text-sm leading-7 text-foreground last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-3 list-disc space-y-2 pl-5 text-sm leading-7 text-foreground marker:text-muted-foreground">{children}</ul>,
  ol: ({ children, start }) => <ol start={start} className="mb-3 list-decimal space-y-2 pl-5 text-sm leading-7 text-foreground marker:text-muted-foreground">{children}</ol>,
  code: makeCodeComponent(
    'font-mono text-[13px] leading-7 text-inherit',
    'rounded-md border border-border/60 bg-background/90 px-1.5 py-0.5 font-mono text-[0.84em] text-foreground shadow-sm',
  ),
  pre: ({ children }) => (
    <pre className="mb-3 overflow-x-auto rounded-2xl border border-border/60 bg-muted/50 px-4 py-4 text-[13px] leading-7 text-foreground shadow-sm">
      {children}
    </pre>
  ),
};

const compactTextComponents: Components = {
  p: ({ children }) => <p className="m-0 whitespace-pre-wrap leading-6 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-1 list-disc space-y-1 pl-5 leading-6 marker:text-muted-foreground">{children}</ul>,
  ol: ({ children, start }) => <ol start={start} className="my-1 list-decimal space-y-1 pl-5 leading-6 marker:text-muted-foreground">{children}</ol>,
  code: makeCodeComponent(
    'font-mono text-inherit',
    'rounded border border-border/60 bg-muted/60 px-1 py-0.5 font-mono text-[0.9em] text-foreground',
  ),
  pre: ({ children }) => (
    <pre className="my-2 max-h-64 overflow-auto rounded-lg border border-border/60 bg-muted/50 p-3 font-mono text-xs leading-5 text-foreground">
      {children}
    </pre>
  ),
};

export function createMarkdownComponents(density: MarkdownDensity = 'comfortable'): Components {
  return {
    ...structuralComponents,
    ...(density === 'compact' ? compactTextComponents : comfortableTextComponents),
  };
}
