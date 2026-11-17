/**
 * Root App component.
 */
import React, { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import AppRouter from './router';
import { AppToaster } from './components/ui/sonner';
import { PluginRequestRecoveryDialog } from './components/plugins/PluginRequestRecoveryDialog';

const App: React.FC = () => {
  const [queryClient] = useState(() => new QueryClient());
  useEffect(() => () => queryClient.clear(), [queryClient]);
  return (
    <QueryClientProvider client={queryClient}>
      <AppRouter />
      <AppToaster />
      <PluginRequestRecoveryDialog />
    </QueryClientProvider>
  );
};

export default App;
