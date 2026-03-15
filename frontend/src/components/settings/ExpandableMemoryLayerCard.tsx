/**
 * Expandable card component for memory layer configuration.
 */

import React from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

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
}) => (
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
      <div
        className={cn('flex-1', !disabled && 'cursor-pointer')}
        onClick={() => !disabled && checked && onExpand(!expanded)}
      >
        <div className="flex items-center justify-between">
          <div>
            <div className={cn('text-sm font-medium', checked && 'text-primary')}>
              {label}
            </div>
            <div className="text-xs leading-5 text-muted-foreground">{description}</div>
          </div>
          {checked && children && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onExpand(!expanded);
              }}
              className="rounded p-1 hover:bg-muted/50"
            >
              {expanded ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </button>
          )}
        </div>
      </div>
    </div>

    {/* Expandable content */}
    {checked && expanded && children && (
      <div className="border-t border-border/40 px-4 py-3">
        <div className="space-y-4">{children}</div>
      </div>
    )}
  </div>
);
