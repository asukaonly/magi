import { useCallback, useEffect } from 'react';
import { useChatShellStore } from '@/stores';
import { registerDesktopOpenSettingsHandler } from '@/runtime/desktop';
import SettingsCenterDialog from './SettingsCenterDialog';

const ShellOverlays = () => {
  const activePanel = useChatShellStore((state) => state.activePanel);
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const clearSettingsNavigationIntent = useChatShellStore((state) => state.clearSettingsNavigationIntent);

  const handleSettingsOpenChange = useCallback((open: boolean) => {
    if (open) {
      setActivePanel('settings');
      return;
    }
    setActivePanel('none');
    clearSettingsNavigationIntent();
  }, [clearSettingsNavigationIntent, setActivePanel]);

  useEffect(() => {
    let dispose: (() => void | Promise<void>) | undefined;
    let cancelled = false;

    const registerHandler = async () => {
      const nextDispose = await registerDesktopOpenSettingsHandler(() => {
        clearSettingsNavigationIntent();
        setActivePanel('settings');
      });
      if (cancelled) {
        await nextDispose();
        return;
      }
      dispose = nextDispose;
    };

    void registerHandler();

    return () => {
      cancelled = true;
      void dispose?.();
    };
  }, [clearSettingsNavigationIntent, setActivePanel]);

  return (
    <SettingsCenterDialog
      open={activePanel === 'settings'}
      onOpenChange={handleSettingsOpenChange}
    />
  );
};

export default ShellOverlays;
