import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import './i18n';
import { RuntimeBootstrap } from './components/connections/RuntimeBootstrap';
import { CenterPathPickerHost } from './components/files/CenterPathPickerHost';
import DesktopQuitPrompt from './components/layout/DesktopQuitPrompt';
import { initializeDesktopLogging } from './runtime/logging';
import { initializeTheme } from './stores/theme';

initializeDesktopLogging();
initializeTheme();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <DesktopQuitPrompt />
    <RuntimeBootstrap />
    <CenterPathPickerHost />
  </React.StrictMode>
);
