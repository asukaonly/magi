import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight } from 'lucide-react';

import { cn } from '@/lib/utils';

interface UnifiedDiffViewerProps {
  patchText: string;
  filename?: string;
  maxHeight?: number;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
}

interface ParsedLine {
  kind: 'add' | 'del' | 'context' | 'hunk' | 'header' | 'meta';
  text: string;
}

interface ParsedDiff {
  lines: ParsedLine[];
  additions: number;
  deletions: number;
}


function parseDiff(patchText: string): ParsedDiff {
  const lines: ParsedLine[] = [];
  let additions = 0;
  let deletions = 0;
  for (const raw of patchText.split('\n')) {
    if (raw.startsWith('+++') || raw.startsWith('---')) {
      lines.push({ kind: 'header', text: raw });
      continue;
    }
    if (raw.startsWith('@@')) {
      lines.push({ kind: 'hunk', text: raw });
      continue;
    }
    if (raw.startsWith('diff --git') || raw.startsWith('index ')) {
      lines.push({ kind: 'meta', text: raw });
      continue;
    }
    if (raw.startsWith('+')) {
      additions += 1;
      lines.push({ kind: 'add', text: raw });
      continue;
    }
    if (raw.startsWith('-')) {
      deletions += 1;
      lines.push({ kind: 'del', text: raw });
      continue;
    }
    lines.push({ kind: 'context', text: raw });
  }
  // Drop the trailing blank line introduced by split('\n').
  if (lines.length > 0 && lines[lines.length - 1].text === '' && lines[lines.length - 1].kind === 'context') {
    lines.pop();
  }
  return { lines, additions, deletions };
}


export function UnifiedDiffViewer({
  patchText,
  filename,
  maxHeight = 400,
  collapsible = true,
  defaultCollapsed = false,
}: UnifiedDiffViewerProps): JSX.Element {
  const { t } = useTranslation('app');
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  const parsed = useMemo(() => parseDiff(patchText), [patchText]);

  const empty = parsed.lines.length === 0 && !patchText.trim();

  return (
    <div className="rounded-md border border-border/60 bg-card/40 text-xs">
      <button
        type="button"
        className={cn(
          'flex w-full items-center justify-between gap-3 px-3 py-2 text-left',
          collapsible ? 'cursor-pointer hover:bg-muted/40' : 'cursor-default',
        )}
        onClick={() => collapsible && setCollapsed(!collapsed)}
      >
        <div className="flex items-center gap-2 min-w-0">
          {collapsible && (
            collapsed
              ? <ChevronRight className="h-3 w-3 text-muted-foreground" />
              : <ChevronDown className="h-3 w-3 text-muted-foreground" />
          )}
          {filename && (
            <span className="font-mono truncate">{filename}</span>
          )}
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          {parsed.additions > 0 && (
            <span className="text-emerald-600">+{parsed.additions}</span>
          )}
          {parsed.deletions > 0 && (
            <span className="text-rose-600">-{parsed.deletions}</span>
          )}
        </div>
      </button>
      {!collapsed && !empty && (
        <pre
          className="overflow-auto px-0 py-1 font-mono leading-5"
          style={{ maxHeight, fontSize: 12 }}
          aria-label={t('chat.delegation.diffAriaLabel', { filename: filename ?? '' })}
        >
          {parsed.lines.map((line, idx) => (
            <div
              key={idx}
              className={cn(
                'whitespace-pre px-3',
                line.kind === 'add' && 'bg-emerald-50/40 text-emerald-800',
                line.kind === 'del' && 'bg-rose-50/40 text-rose-800',
                line.kind === 'hunk' && 'bg-muted/40 text-muted-foreground',
                line.kind === 'header' && 'text-muted-foreground/80',
                line.kind === 'meta' && 'text-muted-foreground/60',
              )}
            >
              {line.text || ' '}
            </div>
          ))}
        </pre>
      )}
      {!collapsed && empty && (
        <div className="px-3 py-2 text-muted-foreground">
          {t('chat.delegation.diffEmpty')}
        </div>
      )}
    </div>
  );
}

export default UnifiedDiffViewer;
