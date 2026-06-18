import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-semibold transition-[background-color,color,box-shadow] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25 disabled:pointer-events-none disabled:opacity-45',
  {
    variants: {
      variant: {
        default:
          'bg-primary text-primary-foreground shadow-[0_8px_18px_hsl(var(--primary)/0.12)] hover:bg-[hsl(var(--primary)/0.92)] hover:shadow-[0_10px_22px_hsl(var(--primary)/0.16)] active:bg-[hsl(var(--primary)/0.86)]',
        secondary:
          'bg-[hsl(var(--secondary)/0.86)] text-secondary-foreground hover:bg-secondary',
        outline:
          'border-0 bg-background/80 text-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.55)] hover:bg-accent/70 hover:text-accent-foreground hover:shadow-[inset_0_0_0_1px_hsl(var(--border)/0.7)]',
        ghost:
          'text-[hsl(var(--foreground)/0.78)] hover:bg-accent/70 hover:text-foreground',
        destructive:
          'bg-destructive text-destructive-foreground shadow-[0_8px_18px_hsl(var(--destructive)/0.12)] hover:bg-destructive/90 hover:shadow-[0_10px_22px_hsl(var(--destructive)/0.16)]',
      },
      size: {
        default: 'h-9 px-3.5 py-2',
        sm: 'h-8 rounded-md px-3',
        lg: 'h-10 px-5',
        icon: 'h-9 w-9',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
  }
);
Button.displayName = 'Button';

export { Button, buttonVariants };
