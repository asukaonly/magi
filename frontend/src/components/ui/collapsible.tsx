import * as React from 'react';
import { ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

interface CollapsibleContextValue {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const CollapsibleContext = React.createContext<CollapsibleContextValue | undefined>(undefined);

function useCollapsibleContext() {
  const context = React.useContext(CollapsibleContext);
  if (!context) {
    throw new Error('Collapsible components must be used within a Collapsible');
  }
  return context;
}

interface CollapsibleProps {
  children: React.ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
}

const Collapsible: React.FC<CollapsibleProps> = ({
  children,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
  className,
}) => {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen);
  const open = controlledOpen !== undefined ? controlledOpen : uncontrolledOpen;
  const handleOpenChange = (newOpen: boolean) => {
    if (controlledOpen === undefined) {
      setUncontrolledOpen(newOpen);
    }
    onOpenChange?.(newOpen);
  };

  return (
    <CollapsibleContext.Provider value={{ open, onOpenChange: handleOpenChange }}>
      <div className={cn('space-y-2', className)}>{children}</div>
    </CollapsibleContext.Provider>
  );
};

interface CollapsibleTriggerProps {
  children: React.ReactNode;
  asChild?: boolean;
  className?: string;
}

const CollapsibleTrigger: React.FC<CollapsibleTriggerProps> = ({
  children,
  className,
}) => {
  const { open, onOpenChange } = useCollapsibleContext();

  return (
    <button
      type="button"
      onClick={() => onOpenChange(!open)}
      className={cn('flex w-full items-center gap-2 text-left', className)}
    >
      <ChevronRight
        className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200', open && 'rotate-90')}
      />
      {children}
    </button>
  );
};

interface CollapsibleContentProps {
  children: React.ReactNode;
  className?: string;
}

const CollapsibleContent: React.FC<CollapsibleContentProps> = ({
  children,
  className,
}) => {
  const { open } = useCollapsibleContext();

  if (!open) return null;

  return (
    <div className={cn('pl-6', className)}>
      {children}
    </div>
  );
};

export { Collapsible, CollapsibleTrigger, CollapsibleContent };
