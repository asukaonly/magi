import type { ChatPanelType } from '@/stores';
import type React from 'react';

export const panelByPathname = (pathname: string): ChatPanelType => {
  if (pathname === '/' || pathname === '/chat') return 'conversation';
  if (pathname === '/settings') return 'settings';
  if (pathname === '/events' || pathname.startsWith('/memory')) return 'memory';
  if (pathname === '/timeline') return 'timeline';
  if (pathname === '/tasks') return 'tasks';
  return 'none';
};

export const shouldRenderChatWorkspace = (pathname: string): boolean =>
  pathname === '/' || pathname === '/chat';

export const shouldClosePanelToChat = (pathname: string): boolean =>
  pathname === '/settings' || pathname === '/events' || pathname.startsWith('/memory');

export const shouldSubmitOnEnter = (
  event: Pick<React.KeyboardEvent<HTMLTextAreaElement>, 'key' | 'shiftKey' | 'nativeEvent'>,
  isComposing: boolean,
): boolean => {
  const nativeEvent = event.nativeEvent as KeyboardEvent & { isComposing?: boolean; keyCode?: number };
  const keyCode = Number(nativeEvent?.keyCode || 0);
  return (
    event.key === 'Enter' &&
    !event.shiftKey &&
    !isComposing &&
    !nativeEvent?.isComposing &&
    keyCode !== 229
  );
};
