import * as React from 'react';
import * as SwitchPrimitives from '@radix-ui/react-switch';
import { cn } from '@/lib/utils';

const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitives.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitives.Root
    className={cn(
      'peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-[background-color,box-shadow] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25 data-[state=checked]:bg-primary data-[state=checked]:shadow-[0_6px_14px_hsl(var(--primary)/0.13)] data-[state=checked]:hover:bg-[hsl(var(--primary)/0.92)] data-[state=unchecked]:bg-[hsl(var(--muted)/0.84)] data-[state=unchecked]:shadow-[inset_0_0_0_1px_hsl(var(--border)/0.64)] data-[state=unchecked]:hover:bg-[hsl(var(--muted)/0.98)]',
      className
    )}
    {...props}
    ref={ref}
  >
    <SwitchPrimitives.Thumb className="pointer-events-none block size-4 rounded-full bg-background shadow-[0_1px_4px_hsl(var(--foreground)/0.14)] ring-0 transition-transform duration-200 data-[state=checked]:translate-x-[18px] data-[state=unchecked]:translate-x-0.5" />
  </SwitchPrimitives.Root>
));
Switch.displayName = SwitchPrimitives.Root.displayName;

export { Switch };
