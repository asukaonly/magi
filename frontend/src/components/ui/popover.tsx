import * as React from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";

import { cn } from "@/lib/utils";

const Popover = PopoverPrimitive.Root;
const PopoverTrigger = PopoverPrimitive.Trigger;

const PopoverContent = React.forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(({ className, align = "center", sideOffset = 4, ...props }, ref) => (
  <PopoverPrimitive.Portal>
    <PopoverPrimitive.Content
      ref={ref}
      align={align}
      sideOffset={sideOffset}
      className={cn(
        // z-[90] sits above Dialog (z-[80]) so popovers opened from
        // inside a dialog (e.g. the time / mood pickers in
        // QuickEntrySheet) are reachable. Sheet uses z-50, so popovers
        // opened from a Sheet still render naturally on top via DOM
        // order. The same z-[90] above a portaled dialog content is
        // harmless — popovers are dismissed before the dialog closes.
        "z-[90] w-auto rounded-md border border-border bg-background p-3 text-foreground shadow-md outline-none",
        "data-[state=open]:animate-in data-[state=closed]:animate-out",
        className
      )}
      {...props}
    />
  </PopoverPrimitive.Portal>
));
PopoverContent.displayName = PopoverPrimitive.Content.displayName;

export { Popover, PopoverTrigger, PopoverContent };
