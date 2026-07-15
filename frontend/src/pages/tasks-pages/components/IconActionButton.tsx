import React from 'react';
import { Button, type ButtonProps } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface IconActionButtonProps extends Omit<ButtonProps, 'children' | 'size'> {
  label: string;
  icon: React.ReactNode;
}

export const IconActionButton = React.forwardRef<HTMLButtonElement, IconActionButtonProps>(({
  label,
  icon,
  className,
  type = 'button',
  ...props
}, ref) => (
  <Button
    {...props}
    ref={ref}
    type={type}
    size="icon"
    aria-label={label}
    title={label}
    className={cn('h-8 w-8 shrink-0', className)}
  >
    {icon}
  </Button>
));
IconActionButton.displayName = 'IconActionButton';
