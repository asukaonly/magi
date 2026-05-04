import { describe, expect, it, beforeEach } from 'vitest';
import { panelByPathname, shouldClosePanelToChat, shouldRenderChatWorkspace, shouldSubmitOnEnter } from '@/pages/chat-route-helpers';
import { useChatShellStore } from '@/stores';

describe('chat shell state', () => {
  const memoryStorage = (() => {
    let cache: Record<string, string> = {};
    return {
      getItem: (key: string) => (key in cache ? cache[key] : null),
      setItem: (key: string, value: string) => {
        cache[key] = value;
      },
      clear: () => {
        cache = {};
      },
    };
  })();

  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', {
      value: memoryStorage,
      writable: true,
    });
    memoryStorage.clear();
    useChatShellStore.setState({
      currentSessionId: null,
      activePanel: 'none',
    });
  });

  it('maps route path to panel type', () => {
    expect(panelByPathname('/settings')).toBe('none');
    expect(panelByPathname('/personality')).toBe('none');
    expect(panelByPathname('/events')).toBe('memory');
    expect(panelByPathname('/memory/overview')).toBe('memory');
    expect(panelByPathname('/timeline')).toBe('timeline');
    expect(panelByPathname('/chat')).toBe('conversation');
    expect(panelByPathname('/')).toBe('conversation');
  });

  it('limits chat workspace host routes to chat-only paths', () => {
    expect(shouldRenderChatWorkspace('/')).toBe(true);
    expect(shouldRenderChatWorkspace('/chat')).toBe(true);
    expect(shouldRenderChatWorkspace('/settings')).toBe(false);
    expect(shouldRenderChatWorkspace('/events')).toBe(false);
    expect(shouldRenderChatWorkspace('/personality')).toBe(false);
  });

  it('returns memory panels to chat when closed', () => {
    expect(shouldClosePanelToChat('/events')).toBe(true);
    expect(shouldClosePanelToChat('/memory/overview')).toBe(true);
    expect(shouldClosePanelToChat('/settings')).toBe(false);
    expect(shouldClosePanelToChat('/personality')).toBe(false);
    expect(shouldClosePanelToChat('/timeline')).toBe(false);
    expect(shouldClosePanelToChat('/chat')).toBe(false);
  });

  it('does not submit while IME composition is active', () => {
    expect(
      shouldSubmitOnEnter(
        {
          key: 'Enter',
          shiftKey: false,
          nativeEvent: { isComposing: true, keyCode: 13 } as KeyboardEvent,
        },
        false
      )
    ).toBe(false);

    expect(
      shouldSubmitOnEnter(
        {
          key: 'Enter',
          shiftKey: false,
          nativeEvent: { isComposing: false, keyCode: 229 } as KeyboardEvent,
        },
        false
      )
    ).toBe(false);

    expect(
      shouldSubmitOnEnter(
        {
          key: 'Enter',
          shiftKey: false,
          nativeEvent: { isComposing: false, keyCode: 13 } as KeyboardEvent,
        },
        true
      )
    ).toBe(false);

    expect(
      shouldSubmitOnEnter(
        {
          key: 'Enter',
          shiftKey: false,
          nativeEvent: { isComposing: false, keyCode: 13 } as KeyboardEvent,
        },
        false
      )
    ).toBe(true);
  });

  it('does not expose deprecated sidebar collapse state anymore', () => {
    const store = useChatShellStore.getState() as unknown as Record<string, unknown>;

    expect(store).not.toHaveProperty('sidebarCollapsed');
    expect(store).not.toHaveProperty('setSidebarCollapsed');
    expect(store).not.toHaveProperty('toggleSidebarCollapsed');
    expect(window.localStorage.getItem('desktop-shell-sidebar-collapsed')).toBeNull();
  });

  it('updates active panel and current session', () => {
    const store = useChatShellStore.getState();
    store.setCurrentSessionId('session-1');
    store.setActivePanel('settings');
    expect(useChatShellStore.getState().currentSessionId).toBe('session-1');
    expect(useChatShellStore.getState().activePanel).toBe('settings');

    store.resetPanel();
    expect(useChatShellStore.getState().activePanel).toBe('none');
  });
});
