/**
 * Expandable card component for memory layer configuration.
 */

import React, { useId } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';

// ============================================================================
// Types
// ============================================================================

export interface ExpandableMemoryLayerCardProps {
  layerKey: string;
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  expanded: boolean;
  onToggle: (checked: boolean) => void;
  onExpand: (expanded: boolean) => void;
  children?: React.ReactNode;
}

// ============================================================================
// Component
// ============================================================================

export const ExpandableMemoryLayerCard: React.FC<ExpandableMemoryLayerCardProps> = ({
  label,
  description,
  checked,
  disabled = false,
  expanded,
  onToggle,
  onExpand,
  children,
}) => {
  const { t } = useTranslation('app');
  const contentId = useId();
  const canExpand = checked && Boolean(children);
  const isExpanded = canExpand && expanded;
  return (
    <div
      className={cn(
        'rounded-xl border transition-all duration-200',
        checked ? 'border-primary/40 bg-primary/5' : 'border-border/60 bg-background/60',
        disabled && 'opacity-60'
      )}
    >
      {/* Header row with toggle */}
      <div className="flex items-center gap-3 px-4 py-3">
        <Switch
          checked={checked}
          disabled={disabled}
          onCheckedChange={onToggle}
          aria-label={label}
        />
        <button
          type="button"
          className="flex flex-1 items-center justify-between rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          disabled={disabled || !canExpand}
          aria-label={t(isExpanded ? 'settings.collapseMemoryLayer' : 'settings.expandMemoryLayer', { name: label })}
          aria-expanded={isExpanded}
          aria-controls={contentId}
          onClick={() => onExpand(!expanded)}
        >
          <span>
            <span className={cn('block text-sm font-medium', checked && 'text-primary')}>
              {label}
            </span>
            <span className="block text-xs leading-5 text-muted-foreground">{description}</span>
          </span>
          {canExpand && (
            <span className="rounded p-1" aria-hidden="true">
              {expanded ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </span>
          )}
        </button>
      </div>

      {/* Expandable content */}
      <div id={contentId} hidden={!isExpanded}>
        {isExpanded && (
          <div className="border-t border-border/40 px-4 py-3">
            <div className="space-y-4">{children}</div>
          </div>
        )}
      </div>
    </div>
  );
};
