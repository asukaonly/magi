import { useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useChatShellStore } from '@/stores';
import SettingsCenterDialog from './SettingsCenterDialog';

const ShellOverlays = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const activePanel = useChatShellStore((state) => state.activePanel);
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);

  const handleSettingsOpenChange = useCallback((open: boolean) => {
    if (open) {
      setActivePanel('settings');
      return;
    }
    setActivePanel('none');
    if (location.pathname === '/settings') {
      navigate('/chat');
    }
  }, [location.pathname, navigate, setActivePanel]);

  return (
    <SettingsCenterDialog
      open={activePanel === 'settings'}
      onOpenChange={handleSettingsOpenChange}
    />
  );
};

export default ShellOverlays;
