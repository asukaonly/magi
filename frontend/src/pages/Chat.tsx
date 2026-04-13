/**
 * Chat page - desktop-focused conversation workspace
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUp, CornerUpLeft, FileText, FolderOpen, ImagePlus, Loader2, Paperclip, Sparkles, Square, UserRound, X } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { motion, useReducedMotion } from 'framer-motion';
import { AutoResizeTextarea } from '@/components/ui/auto-resize-textarea';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { messagesApi } from '@/api';
import type { ChatAttachment } from '@/api';
import { configApi } from '@/api/modules/config';
import { personalityApi } from '@/api/modules/personality';
import { DEFAULT_USER_ID } from '@/constants';
import { getRuntimeConfig } from '@/runtime/config';
import { pickDirectory } from '@/runtime/desktop';
import { useRealtime } from '@/realtime/provider';
import { useChatTraceStore, useConversationStore } from '@/stores';
import ToolchainDrawer from '@/components/chat/ToolchainDrawer';
import { ContextUsageRing } from '@/components/chat/ContextUsageRing';
import { useContextUsageStore } from '@/stores/context-usage';
import { shouldSubmitOnEnter } from './chat-route-helpers';
import {
  normalizeHistoryMessages,
  normalizeTurnUxPlan,
  normalizeTraceSnapshot,
  normalizeTraceSummary,
  shouldShowTraceEntry,
  createClientTurnId,
  type ChatTimelineMessage,
  type ChatTimelineMessageLabel,
  type ChatTimelineReplyPreview,
  normalizeMessageLabel,
} from '@/domain/chat/state';
import { formatChatClockTime, normalizeChatTimestamp } from '@/domain/chat/timestamps';

interface WSMessage {
  type?: string;
  data?: any;
  event?: string;
  channel?: string;
  sid?: string;
  message?: string;
}

interface TurnExecutionControlState {
  state: string;
  label: string | null;
}

const MEMORY_CLEARED_EVENT = 'magi-memory-cleared';
const SESSION_EVENT = 'magi-session-sync';
const USER_ID = DEFAULT_USER_ID;
const MAX_IMAGE_ATTACHMENTS = 5;
const MAX_IMAGE_ATTACHMENT_BYTES = 20 * 1024 * 1024;
const MAX_FILE_ATTACHMENT_BYTES = 50 * 1024 * 1024;
const DEFAULT_CHAT_WORKSPACE_DISPLAY = '~/.magi/chat-workspace';
const IMAGE_ATTACHMENT_ACCEPT = 'image/png,image/jpeg,image/webp';
const FILE_ATTACHMENT_ACCEPT = '.txt,.md,.json,.pdf,.ts,.tsx,.js,.jsx,.py,.rs,.go,.java,.kt,.swift,.c,.cc,.cpp,.h,.hpp,.html,.css,.csv,.xml,.yaml,.yml,.toml,.ini,.log,.sh,.sql,.php,.rb';
const SUPPORTED_IMAGE_MIME_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp']);
const SUPPORTED_PDF_MIME_TYPES = new Set(['application/pdf']);
const SUPPORTED_TEXT_MIME_TYPES = new Set([
  'application/json',
  'application/ld+json',
  'application/sql',
  'application/toml',
  'application/x-httpd-php',
  'application/x-sh',
  'application/xml',
  'application/yaml',
  'text/csv',
  'text/html',
  'text/javascript',
  'text/jsx',
  'text/markdown',
  'text/plain',
  'text/tsx',
  'text/typescript',
  'text/x-c',
  'text/x-c++',
  'text/x-go',
  'text/x-java-source',
  'text/x-python',
  'text/x-ruby',
  'text/x-rust',
  'text/x-shellscript',
  'text/xml',
]);
const SUPPORTED_TEXT_EXTENSIONS = new Set([
  '.c',
  '.cc',
  '.cpp',
  '.css',
  '.csv',
  '.go',
  '.h',
  '.hpp',
  '.html',
  '.ini',
  '.java',
  '.js',
  '.json',
  '.kt',
  '.log',
  '.md',
  '.mjs',
  '.php',
  '.py',
  '.rb',
  '.rs',
  '.sh',
  '.sql',
  '.swift',
  '.toml',
  '.ts',
  '.tsx',
  '.txt',
  '.xml',
  '.yaml',
  '.yml',
]);
const LABEL_EMOJI_OPTIONS = ['😀', '🙂', '😍', '😮', '😂', '😎', '🥹', '🙏', '🔥', '👍'];
const MAX_CUSTOM_LABEL_LENGTH = 4;
const LABEL_POPOVER_WIDTH = 336;
const LABEL_POPOVER_HEIGHT = 272;

type MessageContextMenuState = {
  message: ChatTimelineMessage;
  x: number;
  y: number;
};

type LabelPopoverState = {
  messageId: string;
  x: number;
  y: number;
};

const truncateCustomLabel = (value: string): string => Array.from(value || '').slice(0, MAX_CUSTOM_LABEL_LENGTH).join('');

const toPlainText = (content: string): string => String(content || '')
  .replace(/```[\s\S]*?```/g, (block) => block.replace(/```[\w-]*\n?/g, '').replace(/```/g, ''))
  .replace(/`([^`]+)`/g, '$1')
  .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
  .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
  .replace(/^\s{0,3}#{1,6}\s+/gm, '')
  .replace(/^\s*>\s?/gm, '')
  .replace(/^\s*[-*+]\s+/gm, '')
  .replace(/^\s*\d+\.\s+/gm, '')
  .replace(/\*\*([^*]+)\*\*/g, '$1')
  .replace(/\*([^*]+)\*/g, '$1')
  .replace(/__([^_]+)__/g, '$1')
  .replace(/_([^_]+)_/g, '$1')
  .replace(/\n{3,}/g, '\n\n')
  .trim();

const getLabelPopoverPosition = (rect: DOMRect): { x: number; y: number } => {
  const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1280;
  const viewportHeight = typeof window !== 'undefined' ? window.innerHeight : 800;
  const alignedLeft = Math.max(16, Math.min(rect.left, viewportWidth - LABEL_POPOVER_WIDTH - 16));
  const belowTop = rect.bottom + 8;
  const aboveTop = rect.top - LABEL_POPOVER_HEIGHT - 8;
  return {
    x: alignedLeft,
    y: belowTop + LABEL_POPOVER_HEIGHT <= viewportHeight - 16
      ? belowTop
      : Math.max(16, aboveTop),
  };
};

const buildReplyPreviewFromMessage = (message: ChatTimelineMessage): ChatTimelineReplyPreview | null => {
  const messageId = String(message.messageId || '').trim();
  if (!messageId) {
    return null;
  }
  const excerpt = String(message.content || '').trim();
  return {
    messageId,
    role: message.role,
    messageKind: message.messageKind || null,
    contentExcerpt: excerpt.length > 140 ? `${excerpt.slice(0, 137)}...` : excerpt,
  };
};

type DraftAttachmentKind = 'image' | 'file';

interface DraftAttachment {
  id: string;
  kind: DraftAttachmentKind;
  file: File;
  name: string;
  size: number;
  mimeType: string;
  previewUrl?: string;
}

interface HistoryImagePreview {
  name: string;
  url: string;
}

interface DraftAttachmentResolution {
  nextAttachments: DraftAttachment[];
  droppedForVision: boolean;
  droppedForLimit: boolean;
  droppedOversizedImages: File[];
  droppedOversizedFiles: File[];
  droppedUnsupportedCount: number;
}

const assistantMarkdownComponents: Components = {
  h1: ({ children }) => <h1 className="mb-3 mt-1 text-lg font-semibold leading-snug text-foreground">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-3 mt-5 text-base font-semibold leading-snug text-foreground first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-2 mt-4 text-sm font-semibold leading-snug text-foreground">{children}</h3>,
  p: ({ children }) => <p className="mb-3 whitespace-pre-wrap text-sm leading-7 text-foreground last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5 text-sm leading-7 text-foreground">{children}</ul>,
  ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5 text-sm leading-7 text-foreground">{children}</ol>,
  li: ({ children }) => <li className="pl-1 marker:text-muted-foreground">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="mb-3 border-l-2 border-border/80 pl-3 text-sm italic leading-7 text-muted-foreground">
      {children}
    </blockquote>
  ),
  code: ({ children }) => (
    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-foreground">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="mb-3 overflow-x-auto rounded-xl border border-border/60 bg-muted/40 p-3 text-xs leading-6 text-foreground">
      {children}
    </pre>
  ),
  a: ({ href, children }) => (
    <a href={href} className="text-primary underline decoration-primary/50 underline-offset-2" target="_blank" rel="noreferrer">
      {children}
    </a>
  ),
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
};

const createDraftAttachmentId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `attachment_${crypto.randomUUID()}`;
  }
  return `attachment_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
};

const getFileExtension = (filename: string): string => {
  const dotIndex = filename.lastIndexOf('.');
  if (dotIndex < 0) return '';
  return filename.slice(dotIndex).toLowerCase();
};

const isSupportedImageFile = (file: File): boolean =>
  SUPPORTED_IMAGE_MIME_TYPES.has(String(file.type || '').toLowerCase());

const isSupportedPdfFile = (file: File): boolean => {
  const mimeType = String(file.type || '').toLowerCase();
  return SUPPORTED_PDF_MIME_TYPES.has(mimeType) || getFileExtension(file.name) === '.pdf';
};

const isSupportedTextLikeFile = (file: File): boolean => {
  const mimeType = String(file.type || '').toLowerCase();
  return mimeType.startsWith('text/')
    || SUPPORTED_TEXT_MIME_TYPES.has(mimeType)
    || SUPPORTED_TEXT_EXTENSIONS.has(getFileExtension(file.name));
};

const formatAttachmentSize = (size: number): string => {
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
};

const formatAttachmentKindLabel = (attachment: ChatAttachment, t: (key: string) => string): string => {
  if (attachment.kind === 'image') {
    return t('chat.attachments.addImage');
  }
  return t('chat.attachments.addFile');
};

const normalizeStepStatus = (value: string | null | undefined): string => {
  const normalized = String(value || '').trim();
  if (['completed', 'failed', 'running', 'pending'].includes(normalized)) {
    return normalized;
  }
  return 'pending';
};

const resolveHistoryImagePreviewUrl = (
  sessionId: string | null | undefined,
  attachment: ChatAttachment,
  userId: string = USER_ID,
): string | null => {
  if (attachment.kind !== 'image') {
    return null;
  }
  const normalizedSessionId = String(sessionId || '').trim();
  const attachmentId = String(attachment.attachment_id || '').trim();
  if (!normalizedSessionId || !attachmentId) {
    return null;
  }
  const apiBaseUrl = getRuntimeConfig().apiBaseUrl.replace(/\/+$/, '');
  return `${apiBaseUrl}/messages/session/${encodeURIComponent(normalizedSessionId)}/attachments/${encodeURIComponent(attachmentId)}/content?user_id=${encodeURIComponent(userId)}`;
};

const getWorkspaceDisplayPath = (workspacePath: string | null | undefined): string => {
  const normalizedPath = String(workspacePath || '').trim();
  return normalizedPath || DEFAULT_CHAT_WORKSPACE_DISPLAY;
};

const resolveDraftAttachments = (
  current: DraftAttachment[],
  files: File[],
  coreModelSupportsVision: boolean
): DraftAttachmentResolution => {
  const nextAttachments = [...current];
  let remainingImageSlots = Math.max(
    0,
    MAX_IMAGE_ATTACHMENTS - current.filter((attachment) => attachment.kind === 'image').length
  );
  let droppedForVision = false;
  let droppedForLimit = false;
  const droppedOversizedImages: File[] = [];
  const droppedOversizedFiles: File[] = [];
  let droppedUnsupportedCount = 0;

  files.forEach((file) => {
    if (isSupportedImageFile(file)) {
      if (!coreModelSupportsVision) {
        droppedForVision = true;
        return;
      }
      if (file.size > MAX_IMAGE_ATTACHMENT_BYTES) {
        droppedOversizedImages.push(file);
        return;
      }
      if (remainingImageSlots <= 0) {
        droppedForLimit = true;
        return;
      }
      remainingImageSlots -= 1;
      nextAttachments.push({
        id: createDraftAttachmentId(),
        kind: 'image',
        file,
        name: file.name,
        size: file.size,
        mimeType: file.type,
        previewUrl: URL.createObjectURL(file),
      });
      return;
    }

    if (isSupportedPdfFile(file) || isSupportedTextLikeFile(file)) {
      if (file.size > MAX_FILE_ATTACHMENT_BYTES) {
        droppedOversizedFiles.push(file);
        return;
      }
      nextAttachments.push({
        id: createDraftAttachmentId(),
        kind: 'file',
        file,
        name: file.name,
        size: file.size,
        mimeType: file.type,
      });
      return;
    }

    droppedUnsupportedCount += 1;
  });

  return {
    nextAttachments,
    droppedForVision,
    droppedForLimit,
    droppedOversizedImages,
    droppedOversizedFiles,
    droppedUnsupportedCount,
  };
};

export const ChatPage: React.FC = () => {
  const { t, i18n } = useTranslation('app');
  const shouldReduceMotion = useReducedMotion();
  const { subscribe } = useRealtime();
  const currentSessionId = useConversationStore((state) => state.currentSessionId);
  const currentSession = useConversationStore((state) => (
    state.currentSessionId ? state.sessionsById[state.currentSessionId] || null : null
  ));
  const setCurrentSessionId = useConversationStore((state) => state.setCurrentSessionId);
  const messages = useConversationStore((state) =>
    state.currentSessionId ? (state.messagesBySession[state.currentSessionId] || []) : []
  );
  const upsertSession = useConversationStore((state) => state.upsertSession);
  const appendPendingTurn = useConversationStore((state) => state.appendPendingTurn);
  const upsertMessage = useConversationStore((state) => state.upsertMessage);
  const applyTurnUxPlan = useConversationStore((state) => state.applyTurnUxPlan);
  const receiveAgentResponse = useConversationStore((state) => state.receiveAgentResponse);
  const applyMessageLabel = useConversationStore((state) => state.applyMessageLabel);
  const removeMessage = useConversationStore((state) => state.removeMessage);
  const applyConversationTraceSummary = useConversationStore((state) => state.upsertTraceSummary);
  const resetConversation = useConversationStore((state) => state.reset);

  const drawerOpen = useChatTraceStore((state) => state.drawerOpen);
  const activeTurnId = useChatTraceStore((state) => state.activeTurnId);
  const summaries = useChatTraceStore((state) => state.summaries);
  const snapshots = useChatTraceStore((state) => state.snapshots);
  const upsertSummary = useChatTraceStore((state) => state.upsertSummary);
  const setSnapshot = useChatTraceStore((state) => state.setSnapshot);
  const openDrawer = useChatTraceStore((state) => state.openDrawer);
  const closeDrawer = useChatTraceStore((state) => state.closeDrawer);
  const resetTraceStore = useChatTraceStore((state) => state.reset);
  const updateContextUsage = useContextUsageStore((state) => state.update);

  const [inputValue, setInputValue] = useState('');
  const [aiName, setAiName] = useState<string>('AI');
  const [aiAvatar, setAiAvatar] = useState<string>('');
  const [loadingTrace, setLoadingTrace] = useState(false);
  const [updatingWorkspace, setUpdatingWorkspace] = useState(false);
  const [sendingMessage, setSendingMessage] = useState(false);
  const [coreModelSupportsVision, setCoreModelSupportsVision] = useState(false);
  const [attachmentMenuOpen, setAttachmentMenuOpen] = useState(false);
  const [draftAttachments, setDraftAttachments] = useState<DraftAttachment[]>([]);
  const [historyImagePreview, setHistoryImagePreview] = useState<HistoryImagePreview | null>(null);
  const [cancellingTurnIds, setCancellingTurnIds] = useState<string[]>([]);
  const [executionControlByTurnId, setExecutionControlByTurnId] = useState<Record<string, TurnExecutionControlState>>({});
  const [composerReplyTarget, setComposerReplyTarget] = useState<ChatTimelineReplyPreview | null>(null);
  const [labelPopoverState, setLabelPopoverState] = useState<LabelPopoverState | null>(null);
  const [labelPopoverDraft, setLabelPopoverDraft] = useState('');
  const [messageContextMenu, setMessageContextMenu] = useState<MessageContextMenuState | null>(null);
  const [allowInterjection, setAllowInterjection] = useState(true);
  const [turnActive, setTurnActive] = useState(false);
  const [pendingResponseTurnId, setPendingResponseTurnId] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastHistoryRequestRef = useRef<string | null>(null);
  const isComposingRef = useRef(false);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const draftAttachmentsRef = useRef<DraftAttachment[]>([]);
  const labelPopoverRef = useRef<HTMLDivElement>(null);
  const messageContextMenuRef = useRef<HTMLDivElement>(null);
  const labelInputComposingRef = useRef(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    draftAttachmentsRef.current = draftAttachments;
  }, [draftAttachments]);

  useEffect(() => () => {
    draftAttachmentsRef.current.forEach((attachment) => {
      if (attachment.previewUrl) {
        URL.revokeObjectURL(attachment.previewUrl);
      }
    });
  }, []);

  useEffect(() => {
    let cancelled = false;

    const loadCoreModelCapabilities = async () => {
      try {
        const response = await configApi.get();
        if (!cancelled) {
          setCoreModelSupportsVision(Boolean(response.data?.llm?.selections?.core?.capabilities?.vision));
          const prefs = response.data?.preferences;
          if (prefs) {
            setAllowInterjection(prefs.allow_interjection !== false);
          }
        }
      } catch {
        if (!cancelled) {
          setCoreModelSupportsVision(false);
        }
      }
    };

    void loadCoreModelCapabilities();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!attachmentMenuOpen) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!composerRef.current?.contains(event.target as Node)) {
        setAttachmentMenuOpen(false);
      }
    };

    window.addEventListener('mousedown', handlePointerDown);
    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
    };
  }, [attachmentMenuOpen]);

  const clearDraftAttachments = useCallback(() => {
    setDraftAttachments((current) => {
      current.forEach((attachment) => {
        if (attachment.previewUrl) {
          URL.revokeObjectURL(attachment.previewUrl);
        }
      });
      return [];
    });
  }, []);

  useEffect(() => {
    clearDraftAttachments();
    setAttachmentMenuOpen(false);
    setComposerReplyTarget(null);
    setLabelPopoverState(null);
    setLabelPopoverDraft('');
    setMessageContextMenu(null);
  }, [clearDraftAttachments, currentSessionId]);

  useEffect(() => {
    setCancellingTurnIds([]);
    setExecutionControlByTurnId({});
  }, [currentSessionId]);

  useEffect(() => {
    if (!labelPopoverState) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!labelPopoverRef.current?.contains(event.target as Node)) {
        setLabelPopoverState(null);
        setLabelPopoverDraft('');
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setLabelPopoverState(null);
        setLabelPopoverDraft('');
      }
    };
    const handleScroll = () => {
      setLabelPopoverState(null);
      setLabelPopoverDraft('');
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);
    window.addEventListener('scroll', handleScroll, true);
    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
      window.removeEventListener('scroll', handleScroll, true);
    };
  }, [labelPopoverState]);

  useEffect(() => {
    if (!messageContextMenu) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!messageContextMenuRef.current?.contains(event.target as Node)) {
        setMessageContextMenu(null);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMessageContextMenu(null);
      }
    };
    const handleScroll = () => {
      setMessageContextMenu(null);
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);
    window.addEventListener('scroll', handleScroll, true);
    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
      window.removeEventListener('scroll', handleScroll, true);
    };
  }, [messageContextMenu]);

  const persistSessionWorkspace = useCallback(async (workspacePath: string | null) => {
    if (!currentSessionId) {
      toast.error(t('chat.sessionRequired'));
      return;
    }
    setUpdatingWorkspace(true);
    try {
      const response = await messagesApi.updateSessionWorkspace(USER_ID, currentSessionId, workspacePath);
      upsertSession(response.session);
      window.dispatchEvent(new Event(SESSION_EVENT));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      toast.error(t('chat.workspace.updateFailed', { message }));
    } finally {
      setUpdatingWorkspace(false);
    }
  }, [currentSessionId, t, upsertSession]);

  const handlePickWorkspace = useCallback(async () => {
    const selectedPath = await pickDirectory(currentSession?.workspace_path ?? null);
    if (!selectedPath) {
      return;
    }
    await persistSessionWorkspace(selectedPath);
  }, [currentSession?.workspace_path, persistSessionWorkspace]);

  const removeDraftAttachment = useCallback((attachmentId: string) => {
    setDraftAttachments((current) => {
      const target = current.find((attachment) => attachment.id === attachmentId);
      if (target?.previewUrl) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return current.filter((attachment) => attachment.id !== attachmentId);
    });
  }, []);

  const addDraftAttachments = useCallback((files: File[]) => {
    if (!files.length) {
      return;
    }

    const resolution = resolveDraftAttachments(
      draftAttachmentsRef.current,
      files,
      coreModelSupportsVision
    );

    setDraftAttachments(resolution.nextAttachments);

    if (resolution.droppedForVision) {
      toast.warning(t('chat.attachments.visionRequired'));
    }
    if (resolution.droppedForLimit) {
      toast.warning(t('chat.attachments.imageLimit', { count: MAX_IMAGE_ATTACHMENTS }));
    }
    resolution.droppedOversizedImages.forEach((file) => {
      toast.warning(t('chat.attachments.imageTooLarge', { name: file.name, maxMb: 20 }));
    });
    resolution.droppedOversizedFiles.forEach((file) => {
      toast.warning(t('chat.attachments.fileTooLarge', { name: file.name, maxMb: 50 }));
    });
    if (resolution.droppedUnsupportedCount > 0) {
      toast.warning(t('chat.attachments.unsupportedFiles', { count: resolution.droppedUnsupportedCount }));
    }
  }, [coreModelSupportsVision, t]);

  const handleAttachmentInputChange = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    addDraftAttachments(Array.from(event.target.files || []));
    event.target.value = '';
    setAttachmentMenuOpen(false);
  }, [addDraftAttachments]);

  const handleComposerPaste = useCallback((event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const pastedFiles = Array.from(event.clipboardData?.items || [])
      .filter((item) => item.kind === 'file')
      .map((item) => item.getAsFile())
      .filter((file): file is File => file instanceof File);

    if (pastedFiles.length > 0) {
      addDraftAttachments(pastedFiles);
    }
  }, [addDraftAttachments]);

  const loadTrace = useCallback(
    async (turnId: string) => {
      if (!currentSessionId || !turnId) return;
      setLoadingTrace(true);
      try {
        const result = await messagesApi.getTrace(USER_ID, currentSessionId, turnId);
        const snapshot = normalizeTraceSnapshot(result.trace || undefined);
        if (snapshot) {
          setSnapshot(result.trace!);
        }
      } catch {
        toast.error(t('chat.trace.loadFailed'));
      } finally {
        setLoadingTrace(false);
      }
    },
    [currentSessionId, setSnapshot, t]
  );

  const requestHistory = useCallback(
    async (sessionId: string) => {
      if (!sessionId) return;
      lastHistoryRequestRef.current = sessionId;
      try {
        const history = await messagesApi.getHistory(USER_ID, sessionId);
        const rawMessages = Array.isArray(history.messages) ? history.messages : [];
        useConversationStore.getState().receiveHistory(sessionId, normalizeHistoryMessages(rawMessages));
      } catch {
        toast.error(t('chat.loadHistoryFailed'));
      }
    },
    [t]
  );

  const loadPersonality = useCallback(
    async () => {
      try {
        const response = await personalityApi.getGreeting();
        const data = response.data as { greeting?: string; name?: string; avatar?: string } | undefined;
        if (data) {
          setAiName(data.name || 'AI');
          setAiAvatar(data.avatar || '');
          const sid = useConversationStore.getState().currentSessionId;
          const msgs = sid ? (useConversationStore.getState().messagesBySession[sid] || []) : [];
          if (sid && msgs.length === 0 && data.greeting) {
            receiveAgentResponse({
              sessionId: sid,
              content: String(data.greeting),
              timestamp: Date.now(),
            });
          }
        }
      } catch {
        // Non-critical — keep default AI name
      }
    },
    [receiveAgentResponse]
  );

  const handleExecutionTraceUpdate = useCallback(
    (payload: any) => {
      const sessionId = String(payload?.session_id || currentSessionId || '').trim();
      const turnId = String(payload?.turn_id || '').trim();
      const summary = normalizeTraceSummary(payload?.trace_summary);
      if (!sessionId || !turnId || !summary) return;
      upsertSummary({
        turn_id: summary.turnId,
        mode: summary.mode,
        status: summary.status,
        headline: summary.headline,
        active_steps: summary.activeSteps,
        completed_steps: summary.completedSteps,
        failed_steps: summary.failedSteps,
        duration_seconds: summary.durationSeconds,
        trace_available: summary.traceAvailable,
        orchestration_id: summary.orchestrationId || null,
        plan_summary: summary.planSummary
          ? {
            planner: summary.planSummary.planner || null,
            parallel_mode: summary.planSummary.parallelMode,
            total_steps: summary.planSummary.totalSteps,
            remaining_steps: summary.planSummary.remainingSteps,
            steps: summary.planSummary.steps.map((step) => ({
              subtask_id: step.subtaskId || null,
              label: step.label,
              status: step.status,
            })),
          }
          : null,
      });
      applyConversationTraceSummary(sessionId, turnId, summary);
      if (drawerOpen && activeTurnId === turnId) {
        void loadTrace(turnId);
      }
    },
    [
      activeTurnId,
      applyConversationTraceSummary,
      currentSessionId,
      drawerOpen,
      loadTrace,
      upsertSummary,
    ]
  );

  const handleChatMessageUpsertEvent = useCallback(
    (payload: any) => {
      const sessionId = String(payload?.session_id || currentSessionId || '').trim();
      const rawMessage = payload?.message;
      if (!sessionId || !rawMessage || typeof rawMessage !== 'object') {
        return;
      }
      const normalizedMessage = normalizeHistoryMessages([rawMessage as any])[0];
      if (!normalizedMessage) {
        return;
      }
      upsertMessage(sessionId, normalizedMessage);
      if (payload?.session_summary && typeof payload.session_summary === 'object') {
        upsertSession(payload.session_summary as any);
      }
    },
    [currentSessionId, upsertMessage, upsertSession]
  );

  const handleChatMessageHiddenEvent = useCallback(
    (payload: any) => {
      const sessionId = String(payload?.session_id || currentSessionId || '').trim();
      const messageId = String(payload?.message_id || '').trim();
      if (!sessionId || !messageId) {
        return;
      }
      removeMessage(sessionId, messageId);
      if (payload?.session_summary && typeof payload.session_summary === 'object') {
        upsertSession(payload.session_summary as any);
      }
    },
    [currentSessionId, removeMessage, upsertSession]
  );

  const handleAgentResponseEvent = useCallback(
    (payload: any) => {
      const sessionId = String(payload?.session_id || currentSessionId || '').trim();
      const turnId = String(payload?.turn_id || '').trim();
      const summary = normalizeTraceSummary(payload?.trace_summary);
      const uxPlan = normalizeTurnUxPlan(payload?.ux_plan);
      const assistantSurfaceMode = uxPlan?.assistantSurfaceMode || '';
      const shouldSuppressAssistantBubble = assistantSurfaceMode === 'none';
      if (sessionId) {
        if (shouldSuppressAssistantBubble) {
          if (turnId && uxPlan) {
            applyTurnUxPlan({
              sessionId,
              turnId,
              uxPlan,
              pendingLabel: t('chat.trace.pending'),
            });
          }
        } else {
          receiveAgentResponse({
            sessionId,
            content: String(payload?.content || ''),
            timestamp: normalizeChatTimestamp(payload?.timestamp),
            messageId: payload?.message_id ? String(payload.message_id) : undefined,
            messageKind: payload?.message_kind ? String(payload.message_kind) : null,
            turnId: turnId || undefined,
            traceSummary: summary,
            traceAvailable: Boolean(payload?.trace_available || summary?.traceAvailable),
            uxPlan,
          });
        }
      }
      if (summary) {
        upsertSummary({
          turn_id: summary.turnId,
          mode: summary.mode,
          status: summary.status,
          headline: summary.headline,
          active_steps: summary.activeSteps,
          completed_steps: summary.completedSteps,
          failed_steps: summary.failedSteps,
          duration_seconds: summary.durationSeconds,
          trace_available: summary.traceAvailable,
          orchestration_id: summary.orchestrationId || null,
          plan_summary: summary.planSummary
            ? {
              planner: summary.planSummary.planner || null,
              parallel_mode: summary.planSummary.parallelMode,
              total_steps: summary.planSummary.totalSteps,
              remaining_steps: summary.planSummary.remainingSteps,
              steps: summary.planSummary.steps.map((step) => ({
                subtask_id: step.subtaskId || null,
                label: step.label,
                status: step.status,
              })),
            }
            : null,
        });
        if (sessionId) {
          applyConversationTraceSummary(sessionId, summary.turnId, summary);
        }
      }
      window.dispatchEvent(new Event(SESSION_EVENT));
      if (drawerOpen && activeTurnId === turnId) {
        void loadTrace(turnId);
      }
      if (turnActive && !allowInterjection) {
        setTurnActive(false);
        setPendingResponseTurnId(null);
      }
    },
    [
      activeTurnId,
      allowInterjection,
      applyTurnUxPlan,
      applyConversationTraceSummary,
      currentSessionId,
      drawerOpen,
      loadTrace,
      receiveAgentResponse,
      t,
      turnActive,
      upsertSummary,
    ]
  );

  const handleTurnUxPlanEvent = useCallback(
    (payload: any) => {
      const sessionId = String(payload?.session_id || currentSessionId || '').trim();
      const turnId = String(payload?.turn_id || '').trim();
      const uxPlan = normalizeTurnUxPlan(payload?.ux_plan);
      if (!sessionId || !turnId || !uxPlan) return;
      applyTurnUxPlan({
        sessionId,
        turnId,
        uxPlan,
        pendingLabel: t('chat.trace.pending'),
        messageId: payload?.message_id ? String(payload.message_id) : undefined,
        messageKind: payload?.message_kind ? String(payload.message_kind) : null,
        timestamp: normalizeChatTimestamp(payload?.timestamp),
      });
    },
    [applyTurnUxPlan, currentSessionId, t]
  );

  const handleTurnExecutionControlEvent = useCallback(
    (payload: any) => {
      const sessionId = String(payload?.session_id || currentSessionId || '').trim();
      const turnId = String(payload?.turn_id || '').trim();
      const state = String(payload?.state || '').trim();
      if (!sessionId || !turnId || !state) return;

      setExecutionControlByTurnId((current) => ({
        ...current,
        [turnId]: {
          state,
          label: payload?.label ? String(payload.label).trim() || null : null,
        },
      }));

      if (state === 'cancelling') {
        setCancellingTurnIds((current) => (current.includes(turnId) ? current : [...current, turnId]));
        return;
      }

      if (['cancelled', 'completed', 'failed', 'interrupted', 'merged'].includes(state)) {
        setCancellingTurnIds((current) => current.filter((item) => item !== turnId));
        setTurnActive(false);
        setPendingResponseTurnId(null);
      }
    },
    [currentSessionId]
  );

  const handleRealtimeEvent = useCallback(
    (data: WSMessage) => {
      const eventName = data.event || data.type;

      if (eventName === 'execution_trace_update' && data.data) {
        handleExecutionTraceUpdate(data.data);
        return;
      }

      if (eventName === 'context_usage' && data.data) {
        const cu = data.data as Record<string, unknown>;
        const sid = String(cu.session_id || currentSessionId || '').trim();
        if (sid && typeof cu.used_tokens === 'number' && typeof cu.window_size === 'number') {
          updateContextUsage(sid, {
            used_tokens: cu.used_tokens as number,
            window_size: cu.window_size as number,
            threshold: (cu.threshold as number) || 0,
          });
        }
        return;
      }

      if (eventName === 'turn_ux_plan' && data.data) {
        handleTurnUxPlanEvent(data.data);
        return;
      }

      if (eventName === 'turn_execution_control' && data.data) {
        handleTurnExecutionControlEvent(data.data);
        return;
      }

      if (eventName === 'chat_message_upserted' && data.data) {
        handleChatMessageUpsertEvent(data.data);
        return;
      }

      if (eventName === 'chat_message_hidden' && data.data) {
        handleChatMessageHiddenEvent(data.data);
        return;
      }

      if (eventName === 'agent_response' && data.data) {
        handleAgentResponseEvent(data.data);
      }
    },
    [
      currentSessionId,
      handleAgentResponseEvent,
      handleChatMessageHiddenEvent,
      handleChatMessageUpsertEvent,
      handleTurnExecutionControlEvent,
      handleExecutionTraceUpdate,
      handleTurnUxPlanEvent,
      updateContextUsage,
    ]
  );

  useEffect(() => subscribe(handleRealtimeEvent), [handleRealtimeEvent, subscribe]);

  useEffect(() => {
    if (!currentSessionId) return;
    if (lastHistoryRequestRef.current === currentSessionId) return;
    void requestHistory(currentSessionId);
    void loadPersonality();
  }, [currentSessionId, requestHistory, loadPersonality]);

  useEffect(() => {
    const handleMemoryCleared = () => {
      setCurrentSessionId(null);
      lastHistoryRequestRef.current = null;
      resetTraceStore();
      resetConversation();
      window.dispatchEvent(new Event(SESSION_EVENT));
    };

    window.addEventListener(MEMORY_CLEARED_EVENT, handleMemoryCleared);
    return () => window.removeEventListener(MEMORY_CLEARED_EVENT, handleMemoryCleared);
  }, [resetConversation, resetTraceStore, setCurrentSessionId]);

  const uploadDraftAttachments = useCallback(
    async (sessionId: string, turnId: string, attachments: DraftAttachment[]): Promise<ChatAttachment[]> => {
      if (!attachments.length) {
        return [];
      }
      return Promise.all(
        attachments.map((attachment) => messagesApi.uploadAttachment(USER_ID, sessionId, turnId, attachment.file))
      );
    },
    []
  );

  const handleSendMessage = useCallback(async () => {
    const trimmedMessage = inputValue.trim();
    const queuedAttachments = draftAttachmentsRef.current;
    if (!trimmedMessage && queuedAttachments.length === 0) {
      toast.warning(t('chat.emptyInput'));
      return;
    }
    if (!currentSessionId) {
      toast.error(t('chat.sessionRequired'));
      return;
    }

    const messageContent = trimmedMessage;
    const turnId = createClientTurnId();
    const now = Date.now();
    const replyTarget = composerReplyTarget;
    setSendingMessage(true);
    try {
      const uploadedAttachments = await uploadDraftAttachments(currentSessionId, turnId, queuedAttachments);
      appendPendingTurn({
        sessionId: currentSessionId,
        input: messageContent,
        turnId,
        timestamp: now,
        pendingLabel: t('chat.trace.pending'),
        attachments: uploadedAttachments,
        replyTo: replyTarget,
      });
      setInputValue('');
      clearDraftAttachments();
      setComposerReplyTarget(null);
      if (!allowInterjection) {
        setTurnActive(true);
        setPendingResponseTurnId(turnId);
      }
      const result = await messagesApi.sendMessage({
        user_id: USER_ID,
        session_id: currentSessionId,
        message: messageContent,
        attachments: uploadedAttachments,
        reply_to_message_id: replyTarget?.messageId,
        workspace_path: currentSession?.workspace_path ?? null,
        client_turn_id: turnId,
      });
      if (result.data?.session_id) {
        setCurrentSessionId(String(result.data.session_id));
      }
      window.dispatchEvent(new Event(SESSION_EVENT));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : t('chat.sendFailed');
      toast.error(t('chat.attachments.uploadFailed', { message }));
    } finally {
      setSendingMessage(false);
    }
  }, [
    allowInterjection,
    appendPendingTurn,
    clearDraftAttachments,
    currentSession?.workspace_path,
    currentSessionId,
    composerReplyTarget,
    inputValue,
    setCurrentSessionId,
    t,
    uploadDraftAttachments,
  ]);

  const applyLabelToMessage = useCallback(async (
    message: ChatTimelineMessage,
    nextLabel: {
      kind: string;
      text: string;
    },
  ) => {
    const messageId = String(message.messageId || '').trim();
    if (!currentSessionId || !messageId) {
      return;
    }
    try {
      const response = await messagesApi.labelMessage(USER_ID, currentSessionId, messageId, {
        kind: nextLabel.kind,
        text: nextLabel.text,
        applied_by: 'user',
        source: 'manual',
      });
      const normalizedLabel = normalizeMessageLabel(response.data?.label);
      if (!normalizedLabel) {
        throw new Error('missing_label');
      }
      applyMessageLabel(currentSessionId, messageId, normalizedLabel);
      setLabelPopoverState(null);
      setLabelPopoverDraft('');
    } catch {
      toast.error(t('chat.label.applyFailed'));
    }
  }, [applyMessageLabel, currentSessionId, t]);

  const handleDeleteMessage = useCallback(async (message: ChatTimelineMessage) => {
    const messageId = String(message.messageId || '').trim();
    if (!currentSessionId || !messageId) {
      return;
    }

    try {
      await messagesApi.deleteMessage(USER_ID, currentSessionId, messageId);
      removeMessage(currentSessionId, messageId);
      setMessageContextMenu(null);
      if (labelPopoverState?.messageId === messageId) {
        setLabelPopoverState(null);
        setLabelPopoverDraft('');
      }
    } catch {
      toast.error(t('chat.context.deleteFailed'));
    }
  }, [currentSessionId, labelPopoverState, removeMessage, t]);

  const handleCopyMessage = useCallback(async (
    message: ChatTimelineMessage,
    mode: 'markdown' | 'plain',
  ) => {
    try {
      const text = mode === 'markdown' ? message.content : toPlainText(message.content);
      await navigator.clipboard.writeText(text);
      setMessageContextMenu(null);
    } catch {
      toast.error(t('chat.context.copyFailed'));
    }
  }, [t]);

  const handleLabelDraftChange = useCallback((value: string) => {
    if (labelInputComposingRef.current) {
      setLabelPopoverDraft(value);
      return;
    }
    setLabelPopoverDraft(truncateCustomLabel(value));
  }, []);

  const handleLabelDraftCompositionStart = useCallback(() => {
    labelInputComposingRef.current = true;
  }, []);

  const handleLabelDraftCompositionEnd = useCallback((value: string) => {
    labelInputComposingRef.current = false;
    setLabelPopoverDraft(truncateCustomLabel(value));
  }, []);

  const handleKeyPress = (event: React.KeyboardEvent) => {
    if (shouldSubmitOnEnter(event as React.KeyboardEvent<HTMLTextAreaElement>, isComposingRef.current)) {
      event.preventDefault();
      void handleSendMessage();
    }
  };

  const getAvatar = (role: 'user' | 'assistant') => {
    if (role === 'user') {
      return (
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#d6a893]/70 bg-[#c96b45] text-white shadow-[0_10px_20px_rgba(168,93,62,0.18)]">
          <UserRound className="h-4 w-4" />
        </div>
      );
    }
    const initial = aiName?.charAt(0)?.toUpperCase() || 'A';
    let avatarSrc = aiAvatar;
    if (avatarSrc && avatarSrc.startsWith('/')) {
      const apiBaseUrl = getRuntimeConfig().apiBaseUrl;
      const baseUrl = apiBaseUrl.replace(/\/api\/?$/, '');
      avatarSrc = `${baseUrl}${avatarSrc}`;
    }
    if (avatarSrc && avatarSrc.startsWith('http')) {
      return (
        <div className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary">
          <img src={avatarSrc} alt={aiName} className="h-full w-full object-cover" />
        </div>
      );
    }
    return (
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
        {aiAvatar || initial}
      </div>
    );
  };

  const openTraceDrawer = useCallback((turnId: string) => {
    if (!turnId) return;
    window.setTimeout(() => {
      openDrawer(turnId);
      void loadTrace(turnId);
    }, 0);
  }, [loadTrace, openDrawer]);

  const requestRunCancel = useCallback(async (turnId: string) => {
    const normalizedTurnId = String(turnId || '').trim();
    if (!currentSessionId || !normalizedTurnId) return;
    if (cancellingTurnIds.includes(normalizedTurnId)) return;
    setCancellingTurnIds((current) => [...current, normalizedTurnId]);
    try {
      await messagesApi.cancelRun(USER_ID, currentSessionId, {
        reason: 'user_cancel',
        turnId: normalizedTurnId,
      });
    } catch (error) {
      console.error(error);
      toast.error(t('chat.trace.cancelFailed'));
    } finally {
      setCancellingTurnIds((current) => current.filter((item) => item !== normalizedTurnId));
    }
  }, [cancellingTurnIds, currentSessionId, t]);

  const renderTraceEntry = (message: ChatTimelineMessage) => {
    const turnId = message.turnId;
    const traceSummary = turnId ? summaries[turnId] : undefined;
    const traceDisplayMode = String(message.traceDisplayMode || '').trim() || 'collapsible';
    const canOpenTrace = shouldShowTraceEntry(message, traceSummary);

    if (!turnId || !canOpenTrace) return null;

    const isProminent = traceDisplayMode === 'prominent';

    return (
      <button
        type="button"
        data-trace-variant={isProminent ? 'prominent' : 'default'}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          openTraceDrawer(turnId);
        }}
        className={isProminent
          ? 'inline-flex items-center gap-1 rounded-full border border-primary/25 bg-primary/10 px-2.5 py-1 text-[11px] font-semibold text-primary shadow-sm transition-colors hover:bg-primary/15'
          : 'text-[11px] font-medium text-muted-foreground transition-colors hover:text-primary'}
      >
        {isProminent && <Sparkles className="h-3 w-3" />}
        {t('chat.trace.view')}
      </button>
    );
  };

  const renderStatusCard = (message: ChatTimelineMessage) => {
    const turnId = String(message.turnId || '').trim();
    const executionControl = turnId ? executionControlByTurnId[turnId] : undefined;
    const traceStatus = String(message.traceSummary?.status || '').trim() || 'running';
    const executionState = executionControl?.state || traceStatus;
    const isCancelling = executionState === 'cancelling' || (turnId ? cancellingTurnIds.includes(turnId) : false);
    const showCancelButton = Boolean(turnId) && (executionState === 'running' || executionState === 'cancelling');
    const planSummary = message.traceSummary?.planSummary;
    const defaultExecutionTitleKey = (() => {
      switch (executionState) {
        case 'cancelling':
          return 'chat.trace.execution.cancellingTitle';
        case 'cancelled':
          return 'chat.trace.execution.cancelledTitle';
        case 'completed':
          return 'chat.trace.execution.completedTitle';
        case 'failed':
          return 'chat.trace.execution.failedTitle';
        default:
          return 'chat.trace.execution.runningTitle';
      }
    })();
    const subtitleKey = (() => {
      switch (executionState) {
        case 'cancelling':
          return 'chat.trace.execution.cancellingBody';
        case 'cancelled':
          return 'chat.trace.execution.cancelledBody';
        case 'completed':
          return 'chat.trace.execution.completedBody';
        case 'failed':
          return 'chat.trace.execution.failedBody';
        default:
          return 'chat.trace.execution.runningBody';
      }
    })();
    const statusTitle = executionControl?.label
      || (executionState === 'running' ? (message.traceSummary?.headline || message.content) : '')
      || t(defaultExecutionTitleKey);
    const indicator = executionState === 'cancelled'
      ? <X className="h-4 w-4 text-muted-foreground" />
      : <Loader2 className={`h-4 w-4 text-primary ${executionState === 'running' || executionState === 'cancelling' ? 'animate-spin' : ''}`} />;
    const runningStepIndex = planSummary?.steps.findIndex((step) => normalizeStepStatus(step.status) === 'running') ?? -1;
    const resolvedRunningStep = runningStepIndex >= 0 ? runningStepIndex + 1 : 0;
    const planStageSummary = planSummary
      ? (() => {
        const totalSteps = Math.max(planSummary.totalSteps, planSummary.steps.length, message.traceSummary?.completedSteps || 0);
        if (!totalSteps) return null;
        switch (executionState) {
          case 'cancelling':
            return t('chat.trace.plan.stage.cancelling', {
              completed: message.traceSummary?.completedSteps || 0,
              total: totalSteps,
            });
          case 'cancelled':
            return t('chat.trace.plan.stage.cancelled', {
              completed: message.traceSummary?.completedSteps || 0,
              total: totalSteps,
            });
          case 'completed':
            return t('chat.trace.plan.stage.completed', {
              completed: Math.max(message.traceSummary?.completedSteps || 0, totalSteps),
              total: totalSteps,
            });
          case 'failed':
            return resolvedRunningStep > 0
              ? t('chat.trace.plan.stage.failedStep', {
                current: resolvedRunningStep,
                total: totalSteps,
              })
              : t('chat.trace.plan.stage.failedFallback', {
                completed: message.traceSummary?.completedSteps || 0,
                failed: message.traceSummary?.failedSteps || 0,
              });
          default:
            if (planSummary.parallelMode === 'parallel' && (message.traceSummary?.activeSteps || 0) > 1) {
              return t('chat.trace.plan.stage.runningParallel', {
                active: message.traceSummary?.activeSteps || 0,
                completed: message.traceSummary?.completedSteps || 0,
                total: totalSteps,
              });
            }
            if (resolvedRunningStep > 0) {
              return t('chat.trace.plan.stage.runningStep', {
                current: resolvedRunningStep,
                total: totalSteps,
              });
            }
            return t('chat.trace.plan.stage.runningFallback', {
              completed: message.traceSummary?.completedSteps || 0,
              total: totalSteps,
            });
        }
      })()
      : null;
    const footerKey = (() => {
      switch (executionState) {
        case 'cancelled':
          return 'chat.trace.execution.footerCancelled';
        case 'completed':
          return 'chat.trace.execution.footerCompleted';
        case 'failed':
          return 'chat.trace.execution.footerFailed';
        default:
          return null;
      }
    })();

    return (
      <motion.div
        key={message.id}
        initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: shouldReduceMotion ? 0 : 0.2, ease: 'easeOut' }}
        className="mb-4 flex justify-start"
        data-testid={turnId ? `chat-trace-status-card-${turnId}` : undefined}
      >
        <div className="flex max-w-[76%] gap-3">
          {getAvatar('assistant')}
          <div className="rounded-xl rounded-tl-sm border border-border/35 bg-muted/35 px-4 py-2.5">
            <div className="flex items-center gap-2">
              {indicator}
              <span className="text-sm font-medium text-foreground">{statusTitle}</span>
            </div>
            <div className="mt-1 text-xs leading-5 text-muted-foreground">{t(subtitleKey)}</div>
            {planStageSummary && (
              <div className="mt-3 rounded-lg border border-border/50 bg-background/70 px-3 py-2 text-xs font-medium text-foreground/80">
                {planStageSummary}
              </div>
            )}
            {message.traceSummary && (
              <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                <span className="rounded-full bg-muted px-2.5 py-1">
                  {t('chat.trace.active', { count: message.traceSummary.activeSteps })}
                </span>
                <span className="rounded-full bg-muted px-2.5 py-1">
                  {t('chat.trace.done', { count: message.traceSummary.completedSteps })}
                </span>
                {message.traceSummary.failedSteps > 0 && (
                  <span className="rounded-full bg-rose-50 px-2.5 py-1 text-rose-600">
                    {t('chat.trace.failedCount', { count: message.traceSummary.failedSteps })}
                  </span>
                )}
              </div>
            )}
            {planSummary && planSummary.steps.length > 0 && (
              <div className="mt-3 rounded-lg border border-border/50 bg-background/80 p-3">
                <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                  <span className="rounded-full bg-muted px-2.5 py-1">
                    {planSummary.parallelMode === 'parallel'
                      ? t('chat.trace.plan.parallel')
                      : t('chat.trace.plan.sequential')}
                  </span>
                  <span className="rounded-full bg-muted px-2.5 py-1">
                    {t('chat.trace.plan.totalSteps', { count: planSummary.totalSteps })}
                  </span>
                </div>
                <div className="mt-3 space-y-2">
                  {planSummary.steps.map((step) => {
                    const stepStatus = normalizeStepStatus(step.status);
                    const stepDotClass = stepStatus === 'completed'
                      ? 'bg-emerald-500'
                      : stepStatus === 'failed'
                        ? 'bg-rose-500'
                        : stepStatus === 'running'
                          ? 'bg-primary'
                          : 'bg-muted-foreground/60';
                    const stepContainerClass = stepStatus === 'running'
                      ? 'border-primary/30 bg-primary/5'
                      : stepStatus === 'completed'
                        ? 'border-emerald-200 bg-emerald-50/60'
                        : stepStatus === 'failed'
                          ? 'border-rose-200 bg-rose-50/70'
                          : 'border-border/40 bg-background/70';
                    return (
                      <div
                        key={step.subtaskId || step.label}
                        className={`flex items-start justify-between gap-3 rounded-md border px-3 py-2 ${stepContainerClass}`}
                      >
                        <div className="flex items-start gap-2">
                          <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${stepDotClass}`} />
                          <span className="text-sm leading-6 text-foreground">{step.label}</span>
                        </div>
                        <span className="shrink-0 rounded-full bg-background/80 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                          {t(`chat.trace.plan.stepStatus.${stepStatus}`)}
                        </span>
                      </div>
                    );
                  })}
                </div>
                {planSummary.remainingSteps > 0 && (
                  <div className="mt-3 text-[11px] text-muted-foreground">
                    {t('chat.trace.plan.moreSteps', { count: planSummary.remainingSteps })}
                  </div>
                )}
              </div>
            )}
            {footerKey && (
              <div className="mt-3 text-[11px] text-muted-foreground">
                {t(footerKey)}
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {renderTraceEntry(message)}
              {showCancelButton && turnId && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={isCancelling}
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    void requestRunCancel(turnId);
                  }}
                  className="h-7 rounded-full px-2.5 text-[11px]"
                >
                  {t('chat.trace.cancelRun')}
                </Button>
              )}
            </div>
          </div>
        </div>
      </motion.div>
    );
  };

  const renderUserTurnTraceStatus = (message: ChatTimelineMessage) => {
    if (message.role !== 'user' || !message.traceSummary) return null;
    if (!['interrupted', 'merged'].includes(String(message.traceSummary.status || '').trim())) {
      return null;
    }

    return (
      <div className="mt-2 flex justify-end">
        <div className="flex max-w-[75%] items-center gap-3 rounded-xl border border-border/35 bg-background px-3 py-2">
          <span className="text-xs text-muted-foreground">{message.traceSummary.headline}</span>
          {renderTraceEntry(message)}
        </div>
      </div>
    );
  };

  const renderReplyStrip = (
    replyTo: ChatTimelineReplyPreview | null | undefined,
    align: 'user' | 'assistant',
  ) => {
    if (!replyTo) {
      return null;
    }
    return (
      <div
        className={align === 'user'
          ? 'mb-3 rounded-lg border border-white/70 bg-white/72 px-3 py-2 text-left text-[#5f3427] shadow-[inset_0_1px_0_rgba(255,255,255,0.55)] backdrop-blur-sm'
          : 'mb-3 rounded-lg border border-border/45 bg-background/80 px-3 py-2 text-left text-foreground'}
      >
        <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
          {replyTo.role === 'assistant' ? t('chat.reply.assistant') : t('chat.reply.user')}
        </div>
        <div className="mt-1 line-clamp-2 text-xs leading-5 text-foreground/85">
          {replyTo.contentExcerpt}
        </div>
      </div>
    );
  };

  const renderReplyAction = (message: ChatTimelineMessage) => {
    const replyPreview = buildReplyPreviewFromMessage(message);
    if (!replyPreview) {
      return null;
    }
    return (
      <button
        type="button"
        aria-label={t('chat.reply.action')}
        title={t('chat.reply.action')}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setComposerReplyTarget(replyPreview);
        }}
        className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground transition-colors hover:text-primary"
      >
        <CornerUpLeft className="h-3 w-3" />
        {t('chat.reply.action')}
      </button>
    );
  };

  const renderMessageLabel = (
    label: ChatTimelineMessageLabel | null | undefined,
    align: 'user' | 'assistant',
  ) => {
    if (!label) {
      return null;
    }
    return (
      <div className={`mt-2 flex ${align === 'user' ? 'justify-end' : 'justify-start'}`}>
        <span className="inline-flex h-7 min-w-7 items-center justify-center rounded-full border border-border/60 bg-background px-2 text-sm shadow-sm">
          {label.text}
        </span>
      </div>
    );
  };

  const renderQuickLabelAction = (message: ChatTimelineMessage) => {
    if (message.role !== 'assistant' || !String(message.messageId || '').trim()) {
      return null;
    }
    const isOpen = labelPopoverState?.messageId === message.messageId;
    return (
      <div data-testid="chat-label-action-wrap" className="relative flex items-center">
        <button
          type="button"
          aria-label={t('chat.label.action')}
          title={t('chat.label.action')}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            setMessageContextMenu(null);
            if (isOpen) {
              setLabelPopoverState(null);
              setLabelPopoverDraft('');
              return;
            }
            const triggerRect = (event.currentTarget as HTMLButtonElement).getBoundingClientRect();
            setLabelPopoverState({
              messageId: String(message.messageId),
              ...getLabelPopoverPosition(triggerRect),
            });
            setLabelPopoverDraft('');
          }}
          className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground transition-colors hover:text-primary"
        >
          {t('chat.label.action')}
        </button>
        {isOpen ? (
          <div
            ref={labelPopoverRef}
            data-testid="chat-label-popover"
            className="fixed z-[95] w-[21rem] rounded-2xl border border-border/70 bg-background/95 p-3 shadow-[0_18px_40px_rgba(15,23,42,0.14)] backdrop-blur"
            style={{
              left: labelPopoverState?.x ?? 16,
              top: labelPopoverState?.y ?? 16,
            }}
          >
            <div className="grid grid-cols-5 gap-2">
              {LABEL_EMOJI_OPTIONS.map((emoji) => (
                <button
                  key={emoji}
                  type="button"
                  aria-label={emoji}
                  className="flex h-11 items-center justify-center rounded-xl border border-border/50 bg-muted/35 text-2xl transition-colors hover:border-primary/30 hover:bg-muted/60"
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    void applyLabelToMessage(message, { kind: 'emoji', text: emoji });
                  }}
                >
                  {emoji}
                </button>
              ))}
            </div>
            <div className="mt-3 border-t border-border/60 pt-3">
              <p className="mb-2 text-xs text-muted-foreground">{t('chat.label.customHint')}</p>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={labelPopoverDraft}
                  placeholder={t('chat.label.customPlaceholder')}
                  onChange={(event) => handleLabelDraftChange(event.target.value)}
                  onCompositionStart={handleLabelDraftCompositionStart}
                  onCompositionEnd={(event) => handleLabelDraftCompositionEnd(event.currentTarget.value)}
                  className="h-10 flex-1 rounded-xl border border-border/60 bg-background px-3 text-sm text-foreground outline-none transition-colors focus:border-primary/45"
                />
                <Button
                  type="button"
                  size="sm"
                  disabled={!labelPopoverDraft.trim()}
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    void applyLabelToMessage(message, {
                      kind: 'text',
                      text: labelPopoverDraft.trim(),
                    });
                  }}
                >
                  {t('chat.label.send')}
                </Button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    );
  };

  const renderMessageAttachments = (attachments: ChatAttachment[] | undefined, align: 'user' | 'assistant') => {
    if (!attachments || attachments.length === 0) {
      return null;
    }

    return (
      <div className="mb-3 flex flex-wrap gap-2">
        {attachments.map((attachment) => {
          const previewUrl = resolveHistoryImagePreviewUrl(currentSessionId, attachment);

          return (
            <div
              key={attachment.attachment_id}
              className={align === 'user'
                ? 'flex min-w-[180px] max-w-[260px] items-center gap-3 rounded-xl border border-accent-foreground/10 bg-background/90 px-3 py-2 text-foreground'
                : 'flex min-w-[180px] max-w-[260px] items-center gap-3 rounded-xl border border-border/55 bg-background px-3 py-2 text-foreground'}
            >
              {previewUrl ? (
                <button
                  type="button"
                  onClick={() => setHistoryImagePreview({
                    name: attachment.original_name,
                    url: previewUrl,
                  })}
                  aria-label={t('chat.attachments.openPreview')}
                  className="shrink-0 rounded-xl transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                >
                  <img
                    src={previewUrl}
                    alt={attachment.original_name}
                    className="h-12 w-12 rounded-xl object-cover"
                  />
                </button>
              ) : (
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  {attachment.kind === 'image' ? <ImagePlus className="h-5 w-5" /> : <FileText className="h-5 w-5" />}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-foreground">{attachment.original_name}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {formatAttachmentKindLabel(attachment, t)}
                  {typeof attachment.size_bytes === 'number' ? ` · ${formatAttachmentSize(attachment.size_bytes)}` : ''}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const visibleMessageCount = messages.filter((message) => message.kind !== 'status').length;
  const workspaceDisplayPath = getWorkspaceDisplayPath(currentSession?.workspace_path);
  const hasSessionWorkspaceOverride = Boolean(String(currentSession?.workspace_path || '').trim());

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      className="relative flex h-full min-h-0 flex-col px-3 pb-3 pt-2"
    >
      {currentSessionId && (
        <div className="mb-2 shrink-0 px-2 py-1">
          <div className="flex flex-col gap-2 text-sm text-muted-foreground lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-2">
              <span data-testid="chat-workspace-message-count" className="font-medium text-foreground/80">
                {visibleMessageCount}
              </span>
              <span>{t('chat.workspace.messageCount')}</span>
            </div>
            <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
              <span
                data-testid="chat-workspace-path"
                aria-label={t('chat.workspace.label')}
                className="max-w-[min(56vw,36rem)] truncate text-sm text-foreground/75"
                title={workspaceDisplayPath}
              >
                {workspaceDisplayPath}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  void handlePickWorkspace();
                }}
                disabled={updatingWorkspace}
                className="h-8 rounded-full px-2.5 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              >
                <FolderOpen className="mr-2 h-4 w-4" />
                {t('chat.workspace.change')}
              </Button>
              {hasSessionWorkspaceOverride && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    void persistSessionWorkspace(null);
                  }}
                  disabled={updatingWorkspace}
                  className="h-8 rounded-full px-2.5 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                >
                  <X className="mr-2 h-4 w-4" />
                  {t('chat.workspace.clear')}
                </Button>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
        {messageContextMenu ? (
          <div
            ref={messageContextMenuRef}
            data-testid="chat-message-context-menu"
            className="fixed z-[90] min-w-[180px] rounded-lg border border-border/70 bg-background/95 p-1.5 shadow-[0_14px_36px_rgba(15,23,42,0.16)] backdrop-blur"
            style={{ left: messageContextMenu.x, top: messageContextMenu.y }}
          >
            <button
              type="button"
              onClick={() => {
                const replyPreview = buildReplyPreviewFromMessage(messageContextMenu.message);
                if (replyPreview) {
                  setComposerReplyTarget(replyPreview);
                }
                setMessageContextMenu(null);
              }}
              className="flex w-full items-center rounded-md px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-muted/70"
            >
              {t('chat.context.reply')}
            </button>
            <button
              type="button"
              onClick={() => {
                void handleCopyMessage(messageContextMenu.message, 'markdown');
              }}
              className="flex w-full items-center rounded-md px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-muted/70"
            >
              {t('chat.context.copyMarkdown')}
            </button>
            <button
              type="button"
              onClick={() => {
                void handleCopyMessage(messageContextMenu.message, 'plain');
              }}
              className="flex w-full items-center rounded-md px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-muted/70"
            >
              {t('chat.context.copyPlain')}
            </button>
            <button
              type="button"
              onClick={() => {
                void handleDeleteMessage(messageContextMenu.message);
              }}
              className="flex w-full items-center rounded-md px-3 py-2 text-left text-sm text-destructive transition-colors hover:bg-destructive/10"
            >
              {t('chat.context.delete')}
            </button>
          </div>
        ) : null}
        {messages.map((msg) => (
          msg.kind === 'status' ? (
            renderStatusCard(msg)
          ) : (
            <motion.div
              key={msg.id}
              initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: shouldReduceMotion ? 0 : 0.2, ease: 'easeOut' }}
              className={msg.role === 'user' ? 'mb-5 flex justify-end' : 'mb-5 flex justify-start'}
            >
              <div className={msg.role === 'user' ? 'flex max-w-[75%] flex-row-reverse gap-3' : 'flex max-w-[75%] gap-3'}>
                {getAvatar(msg.role)}
                <div className={msg.role === 'user' ? 'items-end' : 'items-start'}>
                  <div className="mb-1 flex items-center gap-2">
                    <span className="text-xs font-medium text-muted-foreground">
                      {msg.role === 'user' ? t('chat.you') : aiName}
                    </span>
                    <span className="text-[11px] text-muted-foreground">
                      {formatChatClockTime(msg.timestamp, i18n.language)}
                    </span>
                    {renderReplyAction(msg)}
                    {renderQuickLabelAction(msg)}
                    {msg.role === 'assistant' && renderTraceEntry(msg)}
                  </div>
                  <div
                    onContextMenu={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      setLabelPopoverState(null);
                      setLabelPopoverDraft('');
                      setMessageContextMenu({
                        message: msg,
                        x: Math.max(16, event.clientX),
                        y: Math.max(16, event.clientY),
                      });
                    }}
                    className={msg.role === 'user'
                      ? 'rounded-xl rounded-tr-sm border border-transparent bg-[#f6e7de] px-4 py-2.5 text-[#6f3f2d] shadow-[0_14px_34px_rgba(168,93,62,0.09),inset_0_1px_0_rgba(255,255,255,0.42)]'
                      : 'rounded-xl rounded-tl-sm border border-border/35 bg-muted/35 px-4 py-2.5'}
                  >
                    {renderReplyStrip(msg.replyTo, msg.role)}
                    {renderMessageAttachments(msg.attachments, msg.role)}
                    {msg.role === 'assistant' ? (
                      <div className="max-w-none text-current">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={assistantMarkdownComponents}>
                          {msg.content}
                        </ReactMarkdown>
                        {msg.streaming && (
                          <span className="inline-block h-4 w-1.5 animate-pulse rounded-sm bg-current opacity-70" />
                        )}
                      </div>
                    ) : msg.content ? (
                      <p className="m-0 whitespace-pre-wrap text-sm">{msg.content}</p>
                    ) : null}
                  </div>
                  {msg.role === 'user' && msg.reaction && msg.label?.text !== msg.reaction && (
                    <div className="mt-2 flex justify-end">
                      <span className="inline-flex h-7 min-w-7 items-center justify-center rounded-full border border-border/60 bg-background px-2 text-sm shadow-sm">
                        {msg.reaction}
                      </span>
                    </div>
                  )}
                  {renderMessageLabel(msg.label, msg.role)}
                  {msg.role === 'user' && renderUserTurnTraceStatus(msg)}
                </div>
              </div>
            </motion.div>
          )
        ))}

        <div ref={messagesEndRef} />
      </div>

      <div className="mt-2 shrink-0">
        <div
          ref={composerRef}
          className="overflow-hidden rounded-2xl border border-border/45 bg-background shadow-[0_8px_24px_rgba(15,23,42,0.04)]"
        >
          {composerReplyTarget && (
            <div
              data-testid="chat-composer-reply-preview"
              className="mx-5 mt-4 rounded-xl border border-border/50 bg-muted/25 px-3 py-2"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                    {composerReplyTarget.role === 'assistant' ? t('chat.reply.assistant') : t('chat.reply.user')}
                  </div>
                  <div className="mt-1 line-clamp-2 text-sm text-foreground/85">
                    {composerReplyTarget.contentExcerpt}
                  </div>
                </div>
                <button
                  type="button"
                  aria-label={t('chat.reply.cancel')}
                  onClick={() => setComposerReplyTarget(null)}
                  className="rounded-full p-1 text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
          {draftAttachments.length > 0 && (
            <div
              data-testid="chat-composer-attachments"
              className={`flex flex-wrap gap-2 px-5 ${composerReplyTarget ? 'pt-3' : 'pt-4'}`}
            >
              {draftAttachments.map((attachment) => (
                <div
                  key={attachment.id}
                  className="flex min-w-[180px] max-w-[260px] items-center gap-3 rounded-xl border border-border/55 bg-muted/30 px-3 py-2"
                >
                  {attachment.kind === 'image' && attachment.previewUrl ? (
                    <img
                      src={attachment.previewUrl}
                      alt={attachment.name}
                      className="h-11 w-11 shrink-0 rounded-lg object-cover"
                    />
                  ) : (
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <FileText className="h-5 w-5" />
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-foreground">{attachment.name}</div>
                    <div className="text-xs text-muted-foreground">{formatAttachmentSize(attachment.size)}</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeDraftAttachment(attachment.id)}
                    aria-label={t('chat.attachments.remove')}
                    className="rounded-full p-1 text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div
            data-testid="chat-composer-input"
            className={draftAttachments.length > 0 ? 'px-5 pb-0 pt-2.5' : 'px-5 pb-0 pt-3'}
          >
            <AutoResizeTextarea
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
              onCompositionStart={() => {
                isComposingRef.current = true;
              }}
              onCompositionEnd={() => {
                isComposingRef.current = false;
              }}
              placeholder={(!allowInterjection && turnActive) ? t('chat.waitingForReply') : t('chat.inputPlaceholder')}
              onKeyDown={handleKeyPress}
              onPaste={handleComposerPaste}
              disabled={!allowInterjection && turnActive}
              minHeight={88}
              className="max-h-72 resize-none border-0 bg-transparent p-0 text-sm leading-6 shadow-none placeholder:text-muted-foreground/55 focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0 disabled:cursor-not-allowed disabled:bg-transparent disabled:text-muted-foreground"
            />
          </div>
          <div
            data-testid="chat-composer-toolbar"
            className="flex items-center justify-between px-4 pb-3 pt-1"
          >
            <div className="flex items-center gap-1">
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setAttachmentMenuOpen((open) => !open)}
                  aria-label={t('chat.attachments.add')}
                  title={t('chat.attachments.add')}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35"
                >
                  <Paperclip className="h-4 w-4" />
                </button>

              {attachmentMenuOpen && (
                <div className="absolute bottom-full left-0 mb-2 flex w-44 flex-col gap-1 rounded-xl border border-border/60 bg-background p-2 shadow-lg">
                  <button
                    type="button"
                    onClick={() => imageInputRef.current?.click()}
                    disabled={!coreModelSupportsVision}
                    className="flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-muted/55 disabled:cursor-not-allowed disabled:text-muted-foreground"
                  >
                    <ImagePlus className="h-4 w-4" />
                    {t('chat.attachments.addImage')}
                  </button>
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-muted/55"
                  >
                    <FileText className="h-4 w-4" />
                    {t('chat.attachments.addFile')}
                  </button>
                </div>
              )}
              </div>
              <ContextUsageRing sessionId={currentSessionId} />
            </div>
            <button
              type="button"
              onClick={() => {
                if (!allowInterjection && turnActive && pendingResponseTurnId) {
                  void requestRunCancel(pendingResponseTurnId);
                } else {
                  void handleSendMessage();
                }
              }}
              disabled={sendingMessage}
              className="flex h-10 w-10 items-center justify-center rounded-xl bg-foreground text-background transition-colors hover:bg-foreground/92 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
              aria-label={(!allowInterjection && turnActive) ? t('chat.stop') : t('chat.send')}
              title={(!allowInterjection && turnActive) ? t('chat.stop') : t('chat.send')}
            >
              {sendingMessage ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (!allowInterjection && turnActive) ? (
                <Square className="h-4 w-4" />
              ) : (
                <ArrowUp className="h-4 w-4" />
              )}
            </button>
          </div>
          <input
            ref={imageInputRef}
            data-testid="chat-attachments-image-input"
            type="file"
            accept={IMAGE_ATTACHMENT_ACCEPT}
            multiple
            className="hidden"
            onChange={handleAttachmentInputChange}
          />
          <input
            ref={fileInputRef}
            data-testid="chat-attachments-file-input"
            type="file"
            accept={FILE_ATTACHMENT_ACCEPT}
            multiple
            className="hidden"
            onChange={handleAttachmentInputChange}
          />
        </div>
      </div>

      <ToolchainDrawer
        open={drawerOpen}
        onOpenChange={(open) => !open && closeDrawer()}
        loading={loadingTrace}
        snapshot={normalizeTraceSnapshot(snapshots[activeTurnId || ''] || null)}
        title={t('chat.trace.title')}
        subtitle={t('chat.trace.subtitle')}
      />
      <Dialog open={Boolean(historyImagePreview)} onOpenChange={(open) => !open && setHistoryImagePreview(null)}>
        <DialogContent className="max-w-4xl overflow-hidden border-border/70 bg-background/95 p-0">
          <DialogHeader className="sr-only">
            <DialogTitle>{historyImagePreview?.name || t('chat.attachments.previewTitle')}</DialogTitle>
            <DialogDescription>{t('chat.attachments.previewDescription')}</DialogDescription>
          </DialogHeader>
          {historyImagePreview ? (
            <div className="flex max-h-[85vh] flex-col">
              <div className="border-b border-border/60 px-6 py-4 pr-12">
                <div className="truncate text-sm font-medium text-foreground">{historyImagePreview.name}</div>
              </div>
              <div className="flex min-h-0 flex-1 items-center justify-center bg-muted/30 p-4">
                <img
                  src={historyImagePreview.url}
                  alt={historyImagePreview.name}
                  className="max-h-[70vh] w-auto max-w-full rounded-2xl object-contain shadow-sm"
                />
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </motion.div>
  );

};

export default ChatPage;
