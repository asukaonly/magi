/**
 * Root App component.
 */
import React from 'react';
import AppRouter from './router';
import { AppToaster } from './components/ui/sonner';
import { PluginRequestRecoveryDialog } from './components/plugins/PluginRequestRecoveryDialog';

const App: React.FC = () => {
  return (
    <>
      <AppRouter />
      <AppToaster />
      <PluginRequestRecoveryDialog />
    </>
  );
};

export default App;
