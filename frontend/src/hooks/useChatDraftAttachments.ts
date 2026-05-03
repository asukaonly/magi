import { useCallback, useEffect, useRef, useState, type ChangeEvent, type ClipboardEvent, type RefObject } from 'react';
import { toast } from 'sonner';

const MAX_IMAGE_ATTACHMENTS = 5;
const MAX_IMAGE_ATTACHMENT_BYTES = 20 * 1024 * 1024;
const MAX_FILE_ATTACHMENT_BYTES = 50 * 1024 * 1024;

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

type DraftAttachmentKind = 'image' | 'file';

export interface DraftAttachment {
  id: string;
  kind: DraftAttachmentKind;
  file: File;
  name: string;
  size: number;
  mimeType: string;
  previewUrl?: string;
}

export interface DraftMcpResourceAttachment {
  id: string;
  kind: 'mcp_resource';
  serverId: string;
  uri: string;
  name: string;
  mimeType?: string;
  description?: string;
}

export type ComposerDraftItem = DraftAttachment | DraftMcpResourceAttachment;

export const isFileDraftAttachment = (
  item: ComposerDraftItem,
): item is DraftAttachment =>
  item.kind === 'image' || item.kind === 'file';

export const isMcpDraftAttachment = (
  item: ComposerDraftItem,
): item is DraftMcpResourceAttachment => item.kind === 'mcp_resource';

interface DraftAttachmentResolution {
  nextAttachments: DraftAttachment[];
  droppedForVision: boolean;
  droppedForLimit: boolean;
  droppedOversizedImages: File[];
  droppedOversizedFiles: File[];
  droppedUnsupportedCount: number;
}

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

const resolveDraftAttachments = (
  current: DraftAttachment[],
  files: File[],
  coreModelSupportsVision: boolean,
): DraftAttachmentResolution => {
  const nextAttachments = [...current];
  let remainingImageSlots = Math.max(
    0,
    MAX_IMAGE_ATTACHMENTS - current.filter((attachment) => attachment.kind === 'image').length,
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

type UseChatDraftAttachmentsOptions = {
  currentSessionId: string | null;
  coreModelSupportsVision: boolean;
  composerRef: RefObject<HTMLDivElement>;
  onSessionReset?: () => void;
  translate: (key: string, options?: Record<string, unknown>) => string;
};

export function useChatDraftAttachments({
  currentSessionId,
  coreModelSupportsVision,
  composerRef,
  onSessionReset,
  translate,
}: UseChatDraftAttachmentsOptions) {
  const [attachmentMenuOpen, setAttachmentMenuOpen] = useState(false);
  const [draftAttachments, setDraftAttachments] = useState<ComposerDraftItem[]>([]);
  const draftAttachmentsRef = useRef<ComposerDraftItem[]>([]);
  const onSessionResetRef = useRef(onSessionReset);

  useEffect(() => {
    onSessionResetRef.current = onSessionReset;
  }, [onSessionReset]);

  useEffect(() => {
    draftAttachmentsRef.current = draftAttachments;
  }, [draftAttachments]);

  useEffect(() => () => {
    draftAttachmentsRef.current.forEach((attachment) => {
      if (isFileDraftAttachment(attachment) && attachment.previewUrl) {
        URL.revokeObjectURL(attachment.previewUrl);
      }
    });
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
  }, [attachmentMenuOpen, composerRef]);

  const clearDraftAttachments = useCallback(() => {
    setDraftAttachments((current) => {
      if (current.length === 0) {
        return current;
      }
      current.forEach((attachment) => {
        if (isFileDraftAttachment(attachment) && attachment.previewUrl) {
          URL.revokeObjectURL(attachment.previewUrl);
        }
      });
      return [];
    });
  }, []);

  useEffect(() => {
    clearDraftAttachments();
    setAttachmentMenuOpen(false);
    onSessionResetRef.current?.();
  }, [clearDraftAttachments, currentSessionId]);

  const removeDraftAttachment = useCallback((attachmentId: string) => {
    setDraftAttachments((current) => {
      const target = current.find((attachment) => attachment.id === attachmentId);
      if (target && isFileDraftAttachment(target) && target.previewUrl) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return current.filter((attachment) => attachment.id !== attachmentId);
    });
  }, []);

  const addDraftAttachments = useCallback((files: File[]) => {
    if (!files.length) {
      return;
    }

    const fileDrafts = draftAttachmentsRef.current.filter(
      isFileDraftAttachment,
    );
    const otherDrafts = draftAttachmentsRef.current.filter(
      (item) => !isFileDraftAttachment(item),
    );
    const resolution = resolveDraftAttachments(
      fileDrafts,
      files,
      coreModelSupportsVision,
    );

    setDraftAttachments([...otherDrafts, ...resolution.nextAttachments]);

    if (resolution.droppedForVision) {
      toast.warning(translate('chat.attachments.visionRequired'));
    }
    if (resolution.droppedForLimit) {
      toast.warning(translate('chat.attachments.imageLimit', { count: MAX_IMAGE_ATTACHMENTS }));
    }
    resolution.droppedOversizedImages.forEach((file) => {
      toast.warning(translate('chat.attachments.imageTooLarge', { name: file.name, maxMb: 20 }));
    });
    resolution.droppedOversizedFiles.forEach((file) => {
      toast.warning(translate('chat.attachments.fileTooLarge', { name: file.name, maxMb: 50 }));
    });
    if (resolution.droppedUnsupportedCount > 0) {
      toast.warning(translate('chat.attachments.unsupportedFiles', { count: resolution.droppedUnsupportedCount }));
    }
  }, [coreModelSupportsVision, translate]);

  const addMcpResourceDraft = useCallback(
    (resource: Omit<DraftMcpResourceAttachment, 'id' | 'kind'>) => {
      setDraftAttachments((current) => {
        const dupe = current.find(
          (item) =>
            isMcpDraftAttachment(item) &&
            item.serverId === resource.serverId &&
            item.uri === resource.uri,
        );
        if (dupe) {
          return current;
        }
        const next: DraftMcpResourceAttachment = {
          id: createDraftAttachmentId(),
          kind: 'mcp_resource',
          ...resource,
        };
        return [...current, next];
      });
    },
    [],
  );

  const handleAttachmentInputChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    addDraftAttachments(Array.from(event.target.files || []));
    event.target.value = '';
    setAttachmentMenuOpen(false);
  }, [addDraftAttachments]);

  const handleComposerPaste = useCallback((event: ClipboardEvent<HTMLTextAreaElement>) => {
    const pastedFiles = Array.from(event.clipboardData?.items || [])
      .filter((item) => item.kind === 'file')
      .map((item) => item.getAsFile())
      .filter((file): file is File => file instanceof File);

    if (pastedFiles.length > 0) {
      addDraftAttachments(pastedFiles);
    }
  }, [addDraftAttachments]);

  return {
    attachmentMenuOpen,
    draftAttachments,
    clearDraftAttachments,
    removeDraftAttachment,
    addMcpResourceDraft,
    handleAttachmentInputChange,
    handleComposerPaste,
    setAttachmentMenuOpen,
  };
}