import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { normalizeAssistantMarkdownContent } from '@/domain/chat/markdown';
import { cn } from '@/lib/utils';
import { createMarkdownComponents } from './markdown-components';

// Secondary surfaces (cards, drawers, status panels) render markdown at the
// ``compact`` density. The component map is shared with the main chat transcript
// via createMarkdownComponents — see ./markdown-components.tsx.
const compactComponents = createMarkdownComponents('compact');

interface MarkdownBlockProps {
  children: string;
  className?: string;
}

export const MarkdownBlock: React.FC<MarkdownBlockProps> = ({ children, className }) => (
  <div className={cn('max-w-none text-sm leading-6 text-muted-foreground', className)}>
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={compactComponents}>
      {normalizeAssistantMarkdownContent(children)}
    </ReactMarkdown>
  </div>
);
