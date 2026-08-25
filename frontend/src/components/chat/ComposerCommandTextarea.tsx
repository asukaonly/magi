import * as React from 'react';
import { AutoResizeTextarea } from '@/components/ui/auto-resize-textarea';
import { getReasoningModifierDecoration } from '@/domain/chat/reasoning';
import { cn } from '@/lib/utils';

type ComposerCommandTextareaProps = Omit<
  React.ComponentProps<typeof AutoResizeTextarea>,
  'value'
> & {
  value: string;
};

export const ComposerCommandTextarea = React.forwardRef<
  HTMLTextAreaElement,
  ComposerCommandTextareaProps
>(({
  value,
  className,
  disabled,
  onCompositionStart,
  onCompositionEnd,
  onScroll,
  ...props
}, ref) => {
  const [isComposing, setIsComposing] = React.useState(false);
  const [scrollTop, setScrollTop] = React.useState(0);
  const textareaRef = React.useRef<HTMLTextAreaElement | null>(null);
  const decoration = isComposing ? null : getReasoningModifierDecoration(value);

  React.useLayoutEffect(() => {
    const nextScrollTop = textareaRef.current?.scrollTop ?? 0;
    setScrollTop((current) => current === nextScrollTop ? current : nextScrollTop);
  }, [value]);

  return (
    <div className="relative w-full">
      {decoration ? (
        <div
          aria-hidden="true"
          data-testid="composer-command-highlight"
          className={cn(
            'pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words text-[15px] leading-7',
            disabled && 'opacity-50',
          )}
        >
          <div style={{ transform: `translateY(-${scrollTop}px)` }}>
            <span className="text-foreground">{decoration.leadingText}</span>
            <span data-testid="composer-command-prefix" className="text-primary">
              {decoration.modifierText}
            </span>
            <span className="text-foreground">{decoration.trailingText}</span>
          </div>
        </div>
      ) : null}
      <AutoResizeTextarea
        {...props}
        ref={(node) => {
          textareaRef.current = node;
          if (typeof ref === 'function') {
            ref(node);
          } else if (ref) {
            ref.current = node;
          }
        }}
        value={value}
        disabled={disabled}
        onCompositionStart={(event) => {
          setIsComposing(true);
          onCompositionStart?.(event);
        }}
        onCompositionEnd={(event) => {
          setIsComposing(false);
          onCompositionEnd?.(event);
        }}
        onScroll={(event) => {
          setScrollTop(event.currentTarget.scrollTop);
          onScroll?.(event);
        }}
        className={cn(
          className,
          decoration
            && 'text-transparent caret-foreground selection:bg-primary/20 selection:text-foreground',
        )}
      />
    </div>
  );
});

ComposerCommandTextarea.displayName = 'ComposerCommandTextarea';
