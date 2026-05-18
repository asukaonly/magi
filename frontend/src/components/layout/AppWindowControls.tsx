import { useCallback, useEffect, useState } from 'react';
import { Minus, Square, X } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * Custom-drawn min/maximize/close buttons used on platforms where we hide
 * native window decorations (Windows, Linux). On macOS we keep the
 * native traffic lights and this component is not rendered.
 *
 * Imports the Tauri window API lazily so the same module is safe to load
 * in a plain browser dev preview.
 */

type TauriWindow = {
  minimize(): Promise<void>;
  toggleMaximize(): Promise<void>;
  close(): Promise<void>;
};

async function getWindow(): Promise<TauriWindow | null> {
  try {
    const mod = await import('@tauri-apps/api/window');
    return mod.getCurrentWindow() as unknown as TauriWindow;
  } catch {
    return null;
  }
}

export const AppWindowControls = ({ className }: { className?: string }) => {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const win = await getWindow();
      if (!cancelled) {
        setReady(Boolean(win));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleMinimize = useCallback(async () => {
    const win = await getWindow();
    await win?.minimize();
  }, []);

  const handleToggleMaximize = useCallback(async () => {
    const win = await getWindow();
    await win?.toggleMaximize();
  }, []);

  const handleClose = useCallback(async () => {
    const win = await getWindow();
    await win?.close();
  }, []);

  if (!ready) {
    // Reserve the layout slot even before the API binds so the rest of
    // the title bar doesn't reflow.
    return <div className={cn('flex h-full items-stretch', className)} aria-hidden="true" />;
  }

  return (
    <div
      className={cn('flex h-full items-stretch', className)}
      style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
    >
      <WindowButton onClick={handleMinimize} aria-label="Minimize">
        <Minus className="h-3.5 w-3.5" />
      </WindowButton>
      <WindowButton onClick={handleToggleMaximize} aria-label="Maximize">
        <Square className="h-3 w-3" />
      </WindowButton>
      <WindowButton onClick={handleClose} aria-label="Close" variant="close">
        <X className="h-3.5 w-3.5" />
      </WindowButton>
    </div>
  );
};

const WindowButton = ({
  onClick,
  variant,
  children,
  ...rest
}: {
  onClick: () => void;
  variant?: 'close';
  children: React.ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button
    type="button"
    onClick={onClick}
    className={cn(
      'flex w-11 items-center justify-center text-muted-foreground transition-colors',
      variant === 'close'
        ? 'hover:bg-destructive hover:text-destructive-foreground'
        : 'hover:bg-muted hover:text-foreground',
    )}
    {...rest}
  >
    {children}
  </button>
);
