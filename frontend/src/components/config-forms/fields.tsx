import { cn } from '@/lib/utils';
import { Check, ChevronDown } from 'lucide-react';
import { useState, useRef, useEffect, useLayoutEffect, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';

interface OptionItem {
  label: string;
  value: string;
  disabled?: boolean;
}

export function SelectField({
  value,
  onChange,
  options,
  placeholder = 'Select...',
  disabled = false,
  allowEmpty = true,
  className,
  triggerClassName,
  menuClassName,
  ariaLabel,
}: {
  value?: string;
  onChange?: (value: string) => void;
  options: OptionItem[];
  placeholder?: string;
  disabled?: boolean;
  allowEmpty?: boolean;
  className?: string;
  triggerClassName?: string;
  menuClassName?: string;
  ariaLabel?: string;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({});
  const [openUpward, setOpenUpward] = useState(false);
  // Case-insensitive matching for selected option
  const selectedOption = options.find(
    (opt) => opt.value.toLowerCase() === (value || '').toLowerCase()
  );

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      const clickedTrigger = rootRef.current?.contains(target);
      const clickedMenu = menuRef.current?.contains(target);
      if (!clickedTrigger && !clickedMenu) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useLayoutEffect(() => {
    if (!open) {
      return;
    }

    const updateMenuPosition = () => {
      const trigger = triggerRef.current;
      if (!trigger) {
        return;
      }

      const rect = trigger.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const padding = 8;
      const sideOffset = 4;
      const preferredMaxHeight = 240;

      const availableBelow = viewportHeight - rect.bottom - padding - sideOffset;
      const availableAbove = rect.top - padding - sideOffset;
      const shouldOpenUpward = availableBelow < 160 && availableAbove > availableBelow;
      const availableHeight = shouldOpenUpward ? availableAbove : availableBelow;
      const maxHeight = Math.max(120, Math.min(preferredMaxHeight, availableHeight));

      const width = Math.min(rect.width, viewportWidth - padding * 2);
      const left = Math.max(padding, Math.min(rect.left, viewportWidth - padding - width));

      setOpenUpward(shouldOpenUpward);
      setMenuStyle({
        position: 'fixed',
        left,
        width,
        maxHeight,
        zIndex: 1000,
        top: shouldOpenUpward ? rect.top - sideOffset : rect.bottom + sideOffset,
        transform: shouldOpenUpward ? 'translateY(-100%)' : undefined,
      });
    };

    updateMenuPosition();
    window.addEventListener('resize', updateMenuPosition);
    window.addEventListener('scroll', updateMenuPosition, true);
    return () => {
      window.removeEventListener('resize', updateMenuPosition);
      window.removeEventListener('scroll', updateMenuPosition, true);
    };
  }, [open]);

  const handleSelect = (optValue: string) => {
    onChange?.(optValue);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className={cn('relative', className)}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => !disabled && setOpen(!open)}
        disabled={disabled}
        aria-label={ariaLabel}
        className={cn(
          'flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm shadow-[0_1px_2px_rgba(15,23,42,0.05)]',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-600/60',
          disabled && 'cursor-not-allowed opacity-50',
          !selectedOption && 'text-muted-foreground',
          triggerClassName
        )}
      >
        <span>{selectedOption?.label || placeholder}</span>
        <ChevronDown className="h-4 w-4 opacity-50" />
      </button>

      {open && (
        createPortal(
          <div
            ref={menuRef}
            data-select-field-menu=""
            style={menuStyle}
            className={cn(
              'overflow-auto rounded-md border border-border bg-background shadow-[0_12px_24px_rgba(15,23,42,0.08)]',
              openUpward ? 'origin-bottom' : 'origin-top',
              menuClassName
            )}
          >
            {allowEmpty && (
              <button
                type="button"
                onClick={() => handleSelect('')}
                className="flex w-full items-center justify-between px-3 py-2 text-sm hover:bg-muted/50"
              >
                <span className="text-muted-foreground">{placeholder}</span>
                {!value && <Check className="h-4 w-4 text-primary-600" />}
              </button>
            )}
            {options.map((opt) => (
              <button
                type="button"
                key={opt.value}
                onClick={() => {
                  if (!opt.disabled) {
                    handleSelect(opt.value);
                  }
                }}
                disabled={opt.disabled}
                className={cn(
                  'flex w-full items-center justify-between px-3 py-2 text-sm',
                  opt.disabled
                    ? 'cursor-not-allowed text-muted-foreground/60'
                    : 'hover:bg-muted/50'
                )}
              >
                <span>{opt.label}</span>
                {value === opt.value && <Check className="h-4 w-4 text-primary-600" />}
              </button>
            ))}
          </div>,
          document.body
        )
      )}
    </div>
  );
}

SelectField.displayName = 'Select';

export function SwitchField({
  checked,
  onChange,
  disabled = false,
  ariaLabel,
}: {
  checked?: boolean;
  onChange?: (checked: boolean) => void;
  disabled?: boolean;
  ariaLabel?: string;
}): JSX.Element {
  return (
    <label className="inline-flex items-center text-sm">
      <input
        type="checkbox"
        checked={!!checked}
        onChange={(event) => onChange?.(event.target.checked)}
        disabled={disabled}
        aria-label={ariaLabel}
      />
    </label>
  );
}

export function CheckboxGroupField({
  options,
  value = [],
  onChange,
  disabled = false,
}: {
  options: OptionItem[];
  value?: string[];
  onChange?: (value: string[]) => void;
  disabled?: boolean;
}): JSX.Element {
  return (
    <div className="space-y-2">
      {options.map((item) => (
        <label key={item.value} className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={value.includes(item.value)}
            onChange={(event) => {
              const next = new Set(value);
              if (event.target.checked) next.add(item.value);
              else next.delete(item.value);
              onChange?.(Array.from(next));
            }}
            disabled={disabled}
          />
          <span>{item.label}</span>
        </label>
      ))}
    </div>
  );
}
