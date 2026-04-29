import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { normalizeAssistantMarkdownContent } from '@/domain/chat/markdown';
import { cn } from '@/lib/utils';
import { openExternalUrl } from '@/runtime/desktop';

const markdownBlockComponents: Components = {
  p: ({ children }) => <p className="m-0 whitespace-pre-wrap leading-6 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-1 list-disc space-y-1 pl-5 leading-6 marker:text-muted-foreground">{children}</ul>,
  ol: ({ children }) => <ol className="my-1 list-decimal space-y-1 pl-5 leading-6 marker:text-muted-foreground">{children}</ol>,
  li: ({ children }) => <li className="pl-1">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  code: ({ children }) => (
    <code className="rounded border border-border/60 bg-muted/60 px-1 py-0.5 font-mono text-[0.9em] text-foreground">
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="my-2 max-h-64 overflow-auto rounded-lg border border-border/60 bg-muted/50 p-3 font-mono text-xs leading-5 text-foreground">
      {children}
    </pre>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      className="font-medium text-primary underline decoration-primary/45 underline-offset-4 hover:text-primary/80"
      target="_blank"
      rel="noreferrer"
      onClick={(event) => {
        if (!href) return;
        event.preventDefault();
        event.stopPropagation();
        void openExternalUrl(href);
      }}
    >
      {children}
    </a>
  ),
};

interface MarkdownBlockProps {
  children: string;
  className?: string;
}

export const MarkdownBlock: React.FC<MarkdownBlockProps> = ({ children, className }) => (
  <div className={cn('max-w-none text-sm leading-6 text-muted-foreground', className)}>
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownBlockComponents}>
      {normalizeAssistantMarkdownContent(children)}
    </ReactMarkdown>
  </div>
);
