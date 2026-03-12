import type { PropsWithChildren } from 'react';
import { RealtimeProvider } from '@/realtime/provider';

const AppShellProviders = ({ children }: PropsWithChildren) => (
  <RealtimeProvider>
    {children}
  </RealtimeProvider>
);

export default AppShellProviders;
