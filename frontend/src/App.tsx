/**
 * Root App component.
 */
import React from 'react';
import AppRouter from './router';
import { AppToaster } from './components/ui/sonner';

const App: React.FC = () => {
  return (
    <>
      <AppRouter />
      <AppToaster />
    </>
  );
};

export default App;
