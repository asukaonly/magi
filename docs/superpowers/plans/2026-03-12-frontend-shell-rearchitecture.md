# Frontend Shell Rearchitecture Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move routing, realtime connection, session state, and panel orchestration out of `ChatPage` into a true app shell so chat, settings, timeline, personality, and memory views can coexist without losing live updates.

**Architecture:** Introduce a shell-level provider stack inside `MainLayout` that owns route-aware panel state, a single WebSocket connection, and normalized conversation notification state. Refactor `ChatPage` into a focused conversation view that reads from global stores instead of owning application lifecycle. Convert settings/personality/memory navigation into shell-driven routes or overlays so no non-chat surface depends on `ChatPage` being mounted.

**Tech Stack:** React 18, React Router 6, Zustand, TypeScript, Vite, Vitest, Testing Library, native browser WebSocket.

---

## File Structure

### Existing files to modify
- `frontend/src/router/index.tsx`
  Owns route definitions. Split shell routes from content routes so `ChatPage` is only used for chat content.
- `frontend/src/components/layout/MainLayout.tsx`
  Upgrade from visual grid wrapper to application shell host with global providers and shell overlays.
- `frontend/src/components/layout/Sidebar.tsx`
  Read normalized session/unread state from stores instead of ad hoc refresh events.
- `frontend/src/components/layout/SettingsCenterDialog.tsx`
  Move dialog mounting responsibility fully into shell control.
- `frontend/src/pages/Chat.tsx`
  Remove direct socket lifecycle ownership and limit to rendering/sending chat for the active session.
- `frontend/src/pages/Timeline.tsx`
  Read shell panel state from the new route-aware layer rather than mutating it ad hoc.
- `frontend/src/stores/chat-shell.ts`
  Narrow to UI shell state only and stop mixing session/runtime concerns.
- `frontend/src/stores/index.ts`
  Export new shell, realtime, and conversation stores.
- `frontend/src/__tests__/chatShell.test.tsx`
  Update helper assertions after shell responsibilities move.
- `frontend/src/__tests__/sidebarNavigation.test.tsx`
  Add unread indicator and route-host assertions.

### New files to create
- `frontend/src/components/layout/AppShellProviders.tsx`
  Compose shell-level providers in one place.
- `frontend/src/components/layout/ShellRouteHost.tsx`
  Route-aware host that decides which overlay/page mounts under the main shell.
- `frontend/src/components/layout/ShellOverlays.tsx`
  Mount settings dialog and other shell-owned overlays outside page components.
- `frontend/src/stores/realtime-store.ts`
  Track connection state, reconnect attempts, socket lifecycle metadata.
- `frontend/src/stores/conversation-store.ts`
  Normalize sessions, messages, unread counts, previews, and message routing side effects.
- `frontend/src/realtime/client.ts`
  Single native WebSocket client for `/ws` with typed subscribe/send lifecycle.
- `frontend/src/realtime/provider.tsx`
  React provider that connects once, dispatches incoming payloads, and exposes send helpers.
- `frontend/src/realtime/events.ts`
  Shared event type guards and parsers for websocket payloads.
- `frontend/src/pages/Memory.tsx`
  Dedicated route component for memory/events instead of piggybacking on `ChatPage`.
- `frontend/src/pages/Personality.tsx`
  Dedicated route component for personality instead of piggybacking on `ChatPage`.
- `frontend/src/__tests__/realtimeProvider.test.tsx`
  Verify one global connection, routing of incoming events, and cleanup behavior.
- `frontend/src/__tests__/conversationStore.test.ts`
  Verify unread count, active session reset, and incoming chat event handling.
- `frontend/src/__tests__/appShellRouting.test.tsx`
  Verify `/settings`, `/chat`, `/timeline`, `/personality`, and `/events` render from shell correctly.

### Existing files to review during implementation
- `frontend/src/api/modules/messages.ts`
- `frontend/src/runtime/config.ts`
- `frontend/src/pages/chat-state.ts`
- `frontend/src/pages/chat-route-helpers.ts`
- `frontend/src/components/layout/Header.tsx`
- `frontend/src/utils/websocket.ts`
- `frontend/src/hooks/useWebSocket.ts`

## Chunk 1: Shell Boundary And Route Ownership

### Task 1: Define shell route ownership and remove `ChatPage` as panel router

**Files:**
- Create: `frontend/src/components/layout/ShellRouteHost.tsx`
- Create: `frontend/src/pages/Memory.tsx`
- Create: `frontend/src/pages/Personality.tsx`
- Modify: `frontend/src/router/index.tsx`
- Modify: `frontend/src/components/layout/MainLayout.tsx`
- Modify: `frontend/src/pages/Timeline.tsx`
- Test: `frontend/src/__tests__/appShellRouting.test.tsx`
- Test: `frontend/src/__tests__/chatShell.test.tsx`

- [ ] **Step 1: Write the failing routing tests**

```tsx
it('renders settings from the shell without mounting chat content', async () => {
  renderWithRouter('/settings');
  expect(await screen.findByRole('dialog')).toBeInTheDocument();
  expect(screen.queryByPlaceholderText(/chat/i)).not.toBeInTheDocument();
});

it('renders memory and personality as dedicated routes', async () => {
  renderWithRouter('/events');
  expect(await screen.findByText(/memory/i)).toBeInTheDocument();
  renderWithRouter('/personality');
  expect(await screen.findByText(/personality/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify routing fails today**

Run: `cd frontend && npm run test -- --run src/__tests__/appShellRouting.test.tsx src/__tests__/chatShell.test.tsx`

Expected: FAIL because `/settings`, `/events`, and `/personality` still resolve through `ChatPage`.

- [ ] **Step 3: Implement route ownership in the shell**

```tsx
// frontend/src/router/index.tsx
children: [
  { index: true, element: <Navigate to="/chat" replace /> },
  { path: 'chat', element: <ChatPage /> },
  { path: 'timeline', element: <TimelinePage /> },
  { path: 'personality', element: <PersonalityPage /> },
  { path: 'events', element: <MemoryPage /> },
  { path: 'settings', element: <ShellRouteHost overlay="settings" /> },
]
```

```tsx
// frontend/src/components/layout/MainLayout.tsx
return (
  <AppShellProviders>
    <div className="...">
      <Sidebar collapsed={sidebarCollapsed} />
      <main className="h-full overflow-hidden">
        <Outlet />
      </main>
      <ShellOverlays />
    </div>
  </AppShellProviders>
);
```

- [ ] **Step 4: Simplify `ChatPage` route branching**

```tsx
// frontend/src/pages/Chat.tsx
export const ChatPage: React.FC = () => {
  return <ChatConversationView />;
};
```

Expected change: no `location.pathname === '/settings'` or `'/events'` branching remains in `ChatPage`.

- [ ] **Step 5: Re-run routing tests**

Run: `cd frontend && npm run test -- --run src/__tests__/appShellRouting.test.tsx src/__tests__/chatShell.test.tsx`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/router/index.tsx frontend/src/components/layout/MainLayout.tsx frontend/src/components/layout/ShellRouteHost.tsx frontend/src/pages/Memory.tsx frontend/src/pages/Personality.tsx frontend/src/pages/Timeline.tsx frontend/src/__tests__/appShellRouting.test.tsx frontend/src/__tests__/chatShell.test.tsx
git commit -m "refactor: separate shell routes from chat page"
```

## Chunk 2: Global Realtime Layer

### Task 2: Introduce one shell-level native WebSocket provider

**Files:**
- Create: `frontend/src/realtime/client.ts`
- Create: `frontend/src/realtime/events.ts`
- Create: `frontend/src/realtime/provider.tsx`
- Create: `frontend/src/stores/realtime-store.ts`
- Modify: `frontend/src/components/layout/AppShellProviders.tsx`
- Modify: `frontend/src/stores/index.ts`
- Modify: `frontend/src/pages/Chat.tsx`
- Test: `frontend/src/__tests__/realtimeProvider.test.tsx`

- [ ] **Step 1: Write the failing realtime tests**

```tsx
it('opens exactly one websocket for the shell', async () => {
  render(<TestShell />);
  expect(global.WebSocket).toHaveBeenCalledTimes(1);
});

it('keeps websocket connected when navigating away from chat', async () => {
  const { rerender } = renderWithRouter('/chat');
  rerenderWithPath('/timeline');
  expect(mockSocket.close).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run tests to verify current page-owned socket fails**

Run: `cd frontend && npm run test -- --run src/__tests__/realtimeProvider.test.tsx`

Expected: FAIL because socket lifecycle currently lives inside `ChatPage`.

- [ ] **Step 3: Implement a single native websocket client**

```ts
// frontend/src/realtime/client.ts
export class RealtimeClient {
  connect(token?: string): void;
  disconnect(reason?: string): void;
  send(message: RealtimeOutboundMessage): void;
  subscribe(listener: RealtimeListener): () => void;
}
```

```tsx
// frontend/src/realtime/provider.tsx
export const RealtimeProvider: React.FC<PropsWithChildren> = ({ children }) => {
  useEffect(() => {
    client.connect(runtime.sessionToken);
    return () => client.disconnect('shell-unmount');
  }, []);
  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
};
```

- [ ] **Step 4: Move connection status into Zustand**

```ts
// frontend/src/stores/realtime-store.ts
interface RealtimeState {
  connected: boolean;
  lastError: string | null;
  reconnectAttempts: number;
  setConnected: (connected: boolean) => void;
  setLastError: (message: string | null) => void;
}
```

Expected change: remove `window.dispatchEvent(new CustomEvent('magi-chat-connection'))`.

- [ ] **Step 5: Delete dead alternate websocket abstractions**

Remove usage and then remove or inline:
- `frontend/src/utils/websocket.ts`
- `frontend/src/hooks/useWebSocket.ts`

Expected change: only one websocket transport remains, and it uses `/ws` native protocol.

- [ ] **Step 6: Re-run realtime tests and type-check**

Run: `cd frontend && npm run test -- --run src/__tests__/realtimeProvider.test.tsx`

Run: `cd frontend && npm run type-check`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/realtime frontend/src/stores/realtime-store.ts frontend/src/stores/index.ts frontend/src/components/layout/AppShellProviders.tsx frontend/src/pages/Chat.tsx frontend/src/__tests__/realtimeProvider.test.tsx
git commit -m "refactor: move websocket lifecycle into shell"
```

## Chunk 3: Conversation State And Chat Page Slimming

### Task 3: Move session/message state into a global conversation store

**Files:**
- Create: `frontend/src/stores/conversation-store.ts`
- Modify: `frontend/src/api/modules/messages.ts`
- Modify: `frontend/src/pages/Chat.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/pages/chat-state.ts`
- Test: `frontend/src/__tests__/conversationStore.test.ts`
- Test: `frontend/src/__tests__/sidebarNavigation.test.tsx`

- [ ] **Step 1: Write the failing store tests**

```ts
it('increments unread count for inactive sessions on agent response', () => {
  const store = useConversationStore.getState();
  store.setActiveSession('session-a');
  store.receiveAgentResponse({ sessionId: 'session-b', content: 'hello' });
  expect(useConversationStore.getState().unreadBySession['session-b']).toBe(1);
});

it('clears unread count when a session becomes active', () => {
  const store = useConversationStore.getState();
  store.seedUnread('session-b', 2);
  store.setActiveSession('session-b');
  expect(useConversationStore.getState().unreadBySession['session-b']).toBe(0);
});
```

- [ ] **Step 2: Run tests to verify unread/session state does not exist yet**

Run: `cd frontend && npm run test -- --run src/__tests__/conversationStore.test.ts src/__tests__/sidebarNavigation.test.tsx`

Expected: FAIL

- [ ] **Step 3: Implement normalized conversation store**

```ts
interface ConversationState {
  currentSessionId: string | null;
  sessions: Record<string, SessionSummary>;
  orderedSessionIds: string[];
  messagesBySession: Record<string, ChatTimelineMessage[]>;
  unreadBySession: Record<string, number>;
  setActiveSession: (sessionId: string | null) => void;
  hydrateSessions: (sessions: ChatSessionListItem[]) => void;
  receiveHistory: (sessionId: string, messages: ChatTimelineMessage[]) => void;
  receiveAgentResponse: (payload: AgentResponsePayload) => void;
}
```

- [ ] **Step 4: Make `ChatPage` read from the store instead of owning app state**

```tsx
const currentSessionId = useConversationStore((state) => state.currentSessionId);
const messages = useConversationStore((state) => state.messagesBySession[currentSessionId ?? ''] ?? []);
const sendMessage = useRealtime().sendChatMessage;
```

Expected change: `ChatPage` no longer stores `messages`, `connected`, or `currentSessionId` locally.

- [ ] **Step 5: Make sidebar session list reactive**

```tsx
const orderedSessions = useConversationStore(selectOrderedSessions);
const unreadCount = useConversationStore((state) => state.unreadBySession[session.session_id] ?? 0);
```

Expected change: `Sidebar` stops listening for `magi-session-sync` window events.

- [ ] **Step 6: Re-run conversation and sidebar tests**

Run: `cd frontend && npm run test -- --run src/__tests__/conversationStore.test.ts src/__tests__/sidebarNavigation.test.tsx`

Run: `cd frontend && npm run type-check`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/stores/conversation-store.ts frontend/src/api/modules/messages.ts frontend/src/pages/Chat.tsx frontend/src/components/layout/Sidebar.tsx frontend/src/pages/chat-state.ts frontend/src/__tests__/conversationStore.test.ts frontend/src/__tests__/sidebarNavigation.test.tsx
git commit -m "refactor: centralize conversation shell state"
```

## Chunk 4: Shell Notifications And Non-Chat Message Routing

### Task 4: Add unread indicators and typed non-chat event handling in the shell

**Files:**
- Modify: `frontend/src/realtime/events.ts`
- Modify: `frontend/src/realtime/provider.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/components/layout/Header.tsx`
- Modify: `frontend/src/stores/conversation-store.ts`
- Modify: `frontend/src/stores/realtime-store.ts`
- Test: `frontend/src/__tests__/sidebarNavigation.test.tsx`
- Test: `frontend/src/__tests__/realtimeProvider.test.tsx`

- [ ] **Step 1: Write the failing notification tests**

```tsx
it('shows an unread badge on inactive chat sessions when a chat message arrives', async () => {
  emitRealtimeMessage(agentResponseFor('session-b'));
  expect(await screen.findByText('1')).toBeInTheDocument();
});

it('routes non-chat events to dedicated handlers without touching unread chat state', () => {
  emitRealtimeMessage(taskUpdateEvent());
  expect(useConversationStore.getState().unreadBySession).toEqual({});
  expect(useRealtimeStore.getState().lastTaskEvent).toBeDefined();
});
```

- [ ] **Step 2: Run tests to verify shell has no unread indicators yet**

Run: `cd frontend && npm run test -- --run src/__tests__/sidebarNavigation.test.tsx src/__tests__/realtimeProvider.test.tsx`

Expected: FAIL

- [ ] **Step 3: Add typed event dispatch**

```ts
switch (message.type) {
  case 'agent_response':
    conversationStore.receiveAgentResponse(...);
    break;
  case 'execution_trace_update':
    conversationStore.receiveTraceUpdate(...);
    break;
  default:
    realtimeStore.recordSystemEvent(message);
}
```

- [ ] **Step 4: Render unread indicators in the sidebar**

```tsx
{unreadCount > 0 ? (
  <span className="ml-2 inline-flex min-w-5 justify-center rounded-full bg-primary px-1.5 text-[11px] text-primary-foreground">
    {Math.min(unreadCount, 99)}
  </span>
) : null}
```

- [ ] **Step 5: Surface shell-wide connection and event state**

```tsx
const connected = useRealtimeStore((state) => state.connected);
const pendingUnread = useConversationStore(selectTotalUnreadCount);
```

Expected change: `Header` reads from store directly and can show global unread/connection cues.

- [ ] **Step 6: Re-run shell notification tests**

Run: `cd frontend && npm run test -- --run src/__tests__/sidebarNavigation.test.tsx src/__tests__/realtimeProvider.test.tsx`

Run: `cd frontend && npm run type-check`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/realtime/events.ts frontend/src/realtime/provider.tsx frontend/src/components/layout/Sidebar.tsx frontend/src/components/layout/Header.tsx frontend/src/stores/conversation-store.ts frontend/src/stores/realtime-store.ts frontend/src/__tests__/sidebarNavigation.test.tsx frontend/src/__tests__/realtimeProvider.test.tsx
git commit -m "feat: add shell-level chat notifications"
```

## Final Verification

- [ ] Run the focused frontend suite

```bash
cd frontend
npm run test -- --run src/__tests__/appShellRouting.test.tsx src/__tests__/chatShell.test.tsx src/__tests__/realtimeProvider.test.tsx src/__tests__/conversationStore.test.ts src/__tests__/sidebarNavigation.test.tsx
```

Expected: PASS

- [ ] Run the frontend type-check

```bash
cd frontend
npm run type-check
```

Expected: PASS

- [ ] Manual verification

```text
1. Open /chat and send a message.
2. Navigate to /timeline while the backend is still streaming.
3. Confirm the websocket stays connected and the sidebar session shows an unread badge.
4. Open /settings and confirm it appears without mounting chat content.
5. Switch to the unread session and confirm the badge clears.
6. Open /events and /personality and confirm both render as dedicated routes.
```

## Notes

- Do not keep compatibility paths that let both page-owned and shell-owned websocket lifecycles run at once.
- Delete `window` custom-event glue after the new stores are wired.
- Prefer keeping trace rendering logic in chat-specific modules such as `chat-state.ts`; only session-level summaries should move into the conversation store.
- If the backend starts emitting more non-chat event types during implementation, extend `frontend/src/realtime/events.ts` instead of branching directly in page components.
