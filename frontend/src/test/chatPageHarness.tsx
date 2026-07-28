import { cleanup } from '@testing-library/react';
import {
  afterAll,
  afterEach,
  beforeEach,
  describe,
  vi,
} from 'vitest';
import { useConversationStore } from '@/stores/conversation-store';
import { useChatTraceStore } from '@/stores';
import { commandsApi, messagesApi } from '@/api';
import {
  getAskState,
  getPlanState,
  getTodos,
  respondAsk,
  respondPermission,
  updateSessionSettings,
} from '@/api/modules/control';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { personasApi } from '@/api/modules/personas';
import { applyRealtimeStoreProjection } from '@/realtime/store-projection';
import {
  saveRetryableChatSends,
  saveRetryableInlineSkillOperations,
  type RetryableChatSendOperation,
  type RetryableInlineSkillOperation,
} from '@/hooks/chatRetryableSendStorage';

export let realtimeListener: ((message: Record<string, unknown>) => void) | null = null;

const defaultHistorySnapshots = new Map<string, any[]>();
export const consoleErrorSpy = vi
  .spyOn(console, 'error')
  .mockImplementation(() => {});

const hoistedMocks = vi.hoisted(() => ({
  pickDirectoryMock: vi.fn(),
  openExternalUrlMock: vi.fn().mockResolvedValue(undefined),
  convertFileSrcMock: vi.fn((path: string) => `asset://${path}`),
  toastErrorMock: vi.fn(),
  toastWarningMock: vi.fn(),
}));

export const pickDirectoryMock = hoistedMocks.pickDirectoryMock;
export const openExternalUrlMock = hoistedMocks.openExternalUrlMock;
export const convertFileSrcMock = hoistedMocks.convertFileSrcMock;
export const toastErrorMock = hoistedMocks.toastErrorMock;
export const toastWarningMock = hoistedMocks.toastWarningMock;

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'zh-CN' },
  }),
}));

vi.mock('react-router', async () => {
  const actual = await vi.importActual<typeof import('react-router')>('react-router');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

vi.mock('sonner', () => ({
  toast: {
    warning: hoistedMocks.toastWarningMock,
    error: hoistedMocks.toastErrorMock,
    success: vi.fn(),
  },
}));

vi.mock('@/realtime/provider', async () => {
  const actual = await vi.importActual<typeof import('@/realtime/provider')>('@/realtime/provider');
  return {
    ...actual,
    useRealtime: () => ({
      subscribe: (listener: (message: Record<string, unknown>) => void) => {
        realtimeListener = (message: Record<string, unknown>) => {
          applyRealtimeStoreProjection(message);
          listener(message);
        };
        return () => {
          realtimeListener = null;
        };
      },
    }),
  };
});

vi.mock('@/runtime/config', () => ({
  getRuntimeConfig: () => ({
    apiBaseUrl: 'http://127.0.0.1:8000/api',
  }),
}));

vi.mock('@/api/modules/control', () => ({
  getControlSettings: vi.fn().mockResolvedValue({
    permission_mode: 'high_only',
    plan_approval_required: false,
  }),
  getSessionSettings: vi.fn().mockResolvedValue({
    base: { permission_mode: 'high_only', plan_approval_required: false },
    override: null,
    effective: { permission_mode: 'high_only', plan_approval_required: false },
  }),
  listPermissionRules: vi.fn().mockResolvedValue([]),
  updateControlSettings: vi.fn(),
  updateSessionSettings: vi.fn().mockResolvedValue({
    base: { permission_mode: 'high_only', plan_approval_required: false },
    override: { permission_mode: 'off', plan_approval_required: null },
    effective: { permission_mode: 'off', plan_approval_required: false },
  }),
  getPlanState: vi.fn().mockResolvedValue({
    active: false,
    plan_text: null,
    entered_at_ms: null,
    exited_at_ms: null,
  }),
  getTodos: vi.fn().mockResolvedValue([]),
  getAskState: vi.fn().mockResolvedValue(null),
  respondAsk: vi.fn().mockResolvedValue(undefined),
  respondPermission: vi.fn().mockResolvedValue(undefined),
  deletePermissionRule: vi.fn(),
  clearSessionPermissionRules: vi.fn(),
}));

vi.mock('@/api/modules/personas', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/personas')>('@/api/modules/personas');
  return {
    ...actual,
    personasApi: {
      ...actual.personasApi,
      list: vi.fn().mockResolvedValue({ success: true, data: [] }),
      getGreeting: vi.fn().mockResolvedValue({
        success: true,
        data: { name: 'AI', greeting: '', needs_bootstrap: false },
      }),
      bootstrapInit: vi.fn().mockResolvedValue({
        success: true,
        data: { bootstrap_active: false, opening: null },
      }),
    },
  };
});

vi.mock('@/runtime/desktop', () => ({
  pickDirectory: hoistedMocks.pickDirectoryMock,
  openExternalUrl: hoistedMocks.openExternalUrlMock,
}));

vi.mock('@tauri-apps/api/core', () => ({
  convertFileSrc: hoistedMocks.convertFileSrcMock,
}));

vi.mock('@/hooks/useProductTourFlag', () => ({
  useProductTourFlag: () => ({
    completed: true,
    loaded: true,
    markCompleted: vi.fn(),
  }),
}));

vi.mock('@/api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/config')>('@/api/modules/config');
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      get: vi.fn(),
    },
  };
});

vi.mock('@/api', () => ({
  messagesApi: {
    getTrace: vi.fn(),
    uploadAttachment: vi.fn(),
    updateSessionWorkspace: vi.fn(),
    getRecentWorkspaces: vi.fn().mockResolvedValue({ paths: [] }),
    rememberWorkspace: vi.fn().mockResolvedValue({ paths: [] }),
    cancelRun: vi.fn(),
    detachRun: vi.fn(),
    labelMessage: vi.fn(),
    deleteMessage: vi.fn(),
    clearHistory: vi.fn(),
    sendMessage: vi.fn().mockResolvedValue({
      success: true,
      message: 'ok',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
        message_length: 0,
        timestamp: Date.now() / 1000,
      },
    }),
    getHistory: vi.fn().mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-1',
      messages: [],
      count: 0,
    }),
  },
  commandsApi: {
    list: vi.fn().mockResolvedValue([]),
    listSkills: vi.fn().mockResolvedValue([]),
    run: vi.fn(),
    runSkillAsBackground: vi.fn(),
    expandSkill: vi.fn(),
  },
  sensorsApi: {
    getStatus: vi.fn().mockResolvedValue({ sources: [] }),
    getTodaySummary: vi.fn().mockResolvedValue({
      date: '2026-05-16',
      weekday: 5,
      sources: [],
    }),
    requestSync: vi.fn(),
    requestStateFlush: vi.fn(),
    requestAuthorization: vi.fn(),
  },
}));

vi.mock('@/components/chat/ToolchainDrawer', () => ({
  default: () => null,
}));

export const setMockFileSize = (file: File, size: number) => {
  Object.defineProperty(file, 'size', {
    value: size,
    configurable: true,
  });
  return file;
};

export const buildConfigWithVision = (vision: boolean) => ({
  data: {
    ...structuredClone(DEFAULT_SYSTEM_CONFIG),
    llm: {
      ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm),
      selections: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm.selections),
        core: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm.selections.core),
          capabilities: {
            ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm.selections.core.capabilities),
            vision,
          },
          limits: {
            ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm.selections.core.limits),
            context_window: 1_000_000,
          },
        },
      },
    },
  },
});

export const historyWithMessages = (
  messages: Array<Record<string, unknown>>,
  sessionId = 'session-1',
) => ({
  user_id: 'local_user',
  session_id: sessionId,
  messages,
  count: messages.length,
} as any);

export const emptyHistory = (sessionId = 'session-1') => (
  historyWithMessages([], sessionId)
);

export const seedRetryableOperations = ({
  composerTurnId = 'turn-retryable-composer',
  inlineTurnId = 'turn-retryable-inline',
}: {
  composerTurnId?: string;
  inlineTurnId?: string;
} = {}) => {
  const composerOperation: RetryableChatSendOperation = {
    sessionId: 'session-1',
    turnId: composerTurnId,
    createdAtMs: Date.now(),
    draftIdentity: 'old-identity',
    draftSignature: 'old-signature',
    draftKind: 'normal',
    request: {
      user_id: 'local_user',
      session_id: 'session-1',
      message: 'Old composer send',
      client_turn_id: composerTurnId,
    },
    confirmation: {
      kind: 'turn',
      sessionId: 'session-1',
      turnId: composerTurnId,
    },
    pendingTurn: {
      sessionId: 'session-1',
      input: 'Old composer send',
      turnId: composerTurnId,
      timestamp: Date.now(),
      pendingLabel: 'Pending',
    },
  };
  const inlineOperation: RetryableInlineSkillOperation = {
    retryKey: JSON.stringify([
      'session-1',
      null,
      'old-skill',
      [],
    ]),
    createdAtMs: Date.now(),
    request: {
      user_id: 'local_user',
      session_id: 'session-1',
      message: '/old-skill\n\nOld expanded body',
      client_turn_id: inlineTurnId,
    },
    confirmation: {
      kind: 'turn',
      sessionId: 'session-1',
      turnId: inlineTurnId,
    },
  };
  saveRetryableChatSends(new Map([[
    composerOperation.sessionId,
    composerOperation,
  ]]));
  saveRetryableInlineSkillOperations(new Map([[
    inlineOperation.retryKey,
    inlineOperation,
  ]]));
};

export function defineChatPageSuite(
  title: string,
  registerTests: () => void,
): void {
  describe(title, () => {
    afterAll(() => {
      consoleErrorSpy.mockRestore();
    });

    afterEach(() => {
      vi.useRealTimers();
      realtimeListener = null;
      useConversationStore.getState().reset();
      useChatTraceStore.getState().reset();
      cleanup();
      document.body.innerHTML = '';
    });

    beforeEach(() => {
      window.sessionStorage.clear();
      defaultHistorySnapshots.clear();
      realtimeListener = null;
      consoleErrorSpy.mockClear();
      pickDirectoryMock.mockReset();
      pickDirectoryMock.mockResolvedValue(undefined);
      openExternalUrlMock.mockReset();
      openExternalUrlMock.mockResolvedValue(undefined);
      toastErrorMock.mockReset();
      toastWarningMock.mockReset();
      vi.mocked(personasApi.list).mockReset().mockResolvedValue({
        success: true,
        data: [],
      } as any);
      vi.mocked(personasApi.getGreeting).mockReset().mockResolvedValue({
        success: true,
        data: { name: 'AI', greeting: '', needs_bootstrap: false },
      } as any);
      vi.mocked(personasApi.bootstrapInit).mockReset().mockResolvedValue({
        success: true,
        data: { bootstrap_active: false, opening: null },
      } as any);
      vi.mocked(messagesApi.getTrace).mockReset().mockResolvedValue({
        success: true,
        user_id: 'local_user',
        session_id: 'session-1',
        turn_id: 'turn-default',
        trace: null,
      } as any);
      vi.mocked(messagesApi.getRecentWorkspaces).mockReset().mockResolvedValue({
        paths: [],
      } as any);
      vi.mocked(messagesApi.rememberWorkspace).mockReset().mockResolvedValue({
        paths: [],
      } as any);
      vi.mocked(messagesApi.uploadAttachment).mockReset();
      vi.mocked(messagesApi.cancelRun).mockReset();
      vi.mocked(messagesApi.detachRun).mockReset();
      vi.mocked(messagesApi.labelMessage).mockReset();
      vi.mocked(messagesApi.deleteMessage).mockReset();
      vi.mocked(messagesApi.clearHistory).mockReset().mockResolvedValue({
        success: true,
        message: 'ok',
        user_id: 'local_user',
        session_id: 'session-1',
        cleared_message_ids: [],
        cleared_turn_ids: [],
        cleanup_pending: false,
      });
      vi.mocked(respondAsk).mockClear();
      vi.mocked(respondPermission).mockClear();
      vi.mocked(updateSessionSettings).mockClear();
      vi.mocked(getPlanState).mockReset().mockResolvedValue({
        active: false,
        plan_text: null,
        entered_at_ms: null,
        exited_at_ms: null,
      } as any);
      vi.mocked(getTodos).mockReset().mockResolvedValue([]);
      vi.mocked(getAskState).mockReset().mockResolvedValue(null);
      vi.mocked(messagesApi.sendMessage).mockReset().mockResolvedValue({
        success: true,
        message: 'ok',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          message_length: 0,
          timestamp: Date.now() / 1000,
        },
      });
      vi.mocked(messagesApi.getHistory).mockReset().mockImplementation(
        async (_userId, sessionId) => {
          let messages = defaultHistorySnapshots.get(sessionId);
          if (!messages) {
            messages = (
              useConversationStore.getState().messagesBySession[sessionId] || []
            ).filter((message) => (
              Boolean(message.messageId)
              && message.messageId !== 'bootstrap-init-pending'
            )).map((message) => ({
              message_id: message.messageId,
              message_kind: message.messageKind ?? null,
              persona_id: message.personaId ?? null,
              role: message.role,
              content: message.content,
              timestamp: message.timestamp / 1000,
              turn_id: message.turnId ?? null,
              kind: message.kind,
              trace_display_mode: message.traceDisplayMode ?? null,
              allow_trace_collapse: message.allowTraceCollapse,
              trace_summary: message.traceSummary ?? null,
              trace_available: message.traceAvailable,
              run_state: message.runState ?? null,
              attachments: message.attachments,
              reply_to: message.replyTo ? {
                message_id: message.replyTo.messageId,
                role: message.replyTo.role,
                message_kind: message.replyTo.messageKind,
                content_excerpt: message.replyTo.contentExcerpt,
              } : null,
              label: message.label,
              payload: message.payload,
            }));
            defaultHistorySnapshots.set(sessionId, messages);
          }
          return {
            user_id: 'local_user',
            session_id: sessionId,
            messages,
            count: messages.length,
          } as any;
        },
      );
      vi.mocked(commandsApi.list).mockReset().mockResolvedValue([]);
      vi.mocked(commandsApi.listSkills).mockReset().mockResolvedValue([]);
      vi.mocked(commandsApi.run).mockReset();
      vi.mocked(commandsApi.runSkillAsBackground).mockReset();
      vi.mocked(commandsApi.expandSkill).mockReset();
      vi.mocked(configApi.get).mockResolvedValue(
        buildConfigWithVision(true) as any,
      );
      Element.prototype.scrollIntoView = vi.fn();
      URL.createObjectURL = vi.fn(() => 'blob:chat-attachment');
      URL.revokeObjectURL = vi.fn();
      useConversationStore.getState().reset();
      useChatTraceStore.getState().reset();
      useConversationStore.getState().setCurrentSessionId('session-1');
    });

    registerTests();
  });
}
