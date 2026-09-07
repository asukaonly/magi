export type RoutePanelType = 'conversation' | 'memory' | 'timeline' | 'tasks' | 'none';

export const panelByPathname = (pathname: string): RoutePanelType => {
  if (pathname === '/' || pathname === '/chat') return 'conversation';
  if (pathname === '/events' || pathname.startsWith('/memory')) return 'memory';
  if (pathname === '/timeline') return 'timeline';
  if (pathname === '/tasks') return 'tasks';
  return 'none';
};

export const shouldRenderChatWorkspace = (pathname: string): boolean =>
  pathname === '/' || pathname === '/chat';

export const shouldClosePanelToChat = (pathname: string): boolean =>
  pathname === '/events' || pathname.startsWith('/memory');
