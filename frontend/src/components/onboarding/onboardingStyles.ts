export const ONBOARDING_PRIMARY_ACTION_CLASS =
  'h-11 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground shadow-[0_1px_2px_hsl(var(--foreground)/0.08)] transition-[background-color,color,box-shadow,transform] duration-200 hover:bg-[hsl(var(--primary)/0.92)] hover:shadow-[0_2px_6px_-2px_hsl(var(--foreground)/0.14)] active:translate-y-px active:shadow-none focus-visible:ring-primary/20 disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100 disabled:shadow-none';

export const ONBOARDING_SECONDARY_ACTION_CLASS =
  'h-11 rounded-lg px-4 text-sm font-medium text-muted-foreground shadow-none transition-[background-color,color,transform] duration-200 hover:bg-muted/70 hover:text-foreground active:translate-y-px active:bg-muted focus-visible:ring-foreground/15 disabled:opacity-40';

export const ONBOARDING_FIELD_CLASS =
  'rounded-md bg-card text-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.72),0_1px_2px_hsl(var(--foreground)/0.035)] outline-none transition-[background-color,box-shadow] duration-200 placeholder:text-muted-foreground/60 hover:shadow-[inset_0_0_0_1px_hsl(var(--border)/0.95),0_1px_2px_hsl(var(--foreground)/0.05)] focus:bg-card focus:ring-2 focus:ring-primary/20 focus:shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.28),0_4px_18px_-14px_hsl(var(--primary)/0.42)] motion-reduce:transition-none';

// 选中态:中性纸面 + 低调的 primary 细描边,不用彩色填充(去「AI 应用」的粉色 surface)。
export const ONBOARDING_SELECTED_SURFACE_CLASS =
  'bg-card shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.38)]';
