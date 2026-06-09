import { useState } from 'react';
import { Check, Copy } from 'lucide-react';

import { cn } from '@/lib/utils';

export type CodeBlockDensity = 'comfortable' | 'compact';

interface CodeBlockProps {
  /** Raw code text (already de-fenced — no surrounding ``` markers). */
  code: string;
  /** Language tag parsed from the markdown fence (e.g. ``python``), if any. */
  language?: string;
  density?: CodeBlockDensity;
}

const COPIED_RESET_MS = 1500;

/**
 * A fenced-code panel with a thin header (language label + copy button).
 *
 * Used by the shared markdown component map (markdown-components.tsx) for every
 * fenced code block. The copy button writes the raw code to the clipboard and
 * flips to a check for brief confirmation. Clicks are kept from bubbling so the
 * button never triggers the surrounding chat message's selection / context menu.
 */
export function CodeBlock({ code, language, density = 'comfortable' }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const compact = density === 'compact';

  const handleCopy = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    void navigator.clipboard
      .writeText(code)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), COPIED_RESET_MS);
      })
      .catch(() => {
        // Clipboard can reject (permissions / insecure context). Leave the icon
        // unchanged rather than lying about success.
      });
  };

  return (
    <div
      className={cn(
        'group/codeblock my-3 overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm',
        compact && 'my-2 rounded-lg',
      )}
    >
      <div
        className={cn(
          'flex items-center justify-between border-b border-border/50 bg-muted/40 px-3',
          compact ? 'py-1' : 'py-1.5',
        )}
      >
        <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{language ?? ''}</span>
        <button
          type="button"
          onClick={handleCopy}
          aria-label={copied ? '已复制' : '复制代码'}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre
        className={cn(
          'font-mono text-foreground',
          compact ? 'max-h-72 overflow-auto px-3 py-2.5 text-xs leading-5' : 'overflow-x-auto px-4 py-3 text-[13px] leading-7',
        )}
      >
        <code>{code}</code>
      </pre>
    </div>
  );
}
