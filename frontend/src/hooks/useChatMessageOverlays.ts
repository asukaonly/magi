import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatTimelineMessage } from '@/domain/chat/state';

const MAX_CUSTOM_LABEL_LENGTH = 4;

const truncateCustomLabel = (value: string): string => Array.from(value || '').slice(0, MAX_CUSTOM_LABEL_LENGTH).join('');

export type MessageContextMenuState = {
  message: ChatTimelineMessage;
  x: number;
  y: number;
};

export type LabelPopoverState = {
  messageId: string;
  x: number;
  y: number;
};

export function useChatMessageOverlays(currentSessionId: string | null) {
  const [labelPopoverState, setLabelPopoverState] = useState<LabelPopoverState | null>(null);
  const [labelPopoverDraft, setLabelPopoverDraft] = useState('');
  const [messageContextMenu, setMessageContextMenu] = useState<MessageContextMenuState | null>(null);
  const labelPopoverRef = useRef<HTMLDivElement>(null);
  const messageContextMenuRef = useRef<HTMLDivElement>(null);
  const labelInputComposingRef = useRef(false);

  const closeLabelPopover = useCallback(() => {
    setLabelPopoverState(null);
    setLabelPopoverDraft('');
  }, []);

  const closeMessageContextMenu = useCallback(() => {
    setMessageContextMenu(null);
  }, []);

  const openLabelPopover = useCallback((messageId: string, position: { x: number; y: number }) => {
    setLabelPopoverState({
      messageId,
      x: position.x,
      y: position.y,
    });
    setLabelPopoverDraft('');
  }, []);

  const openMessageContextMenu = useCallback((message: ChatTimelineMessage, position: { x: number; y: number }) => {
    setMessageContextMenu({
      message,
      x: position.x,
      y: position.y,
    });
  }, []);

  useEffect(() => {
    closeLabelPopover();
    closeMessageContextMenu();
  }, [closeLabelPopover, closeMessageContextMenu, currentSessionId]);

  useEffect(() => {
    if (!labelPopoverState) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!labelPopoverRef.current?.contains(event.target as Node)) {
        closeLabelPopover();
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeLabelPopover();
      }
    };
    const handleScroll = () => {
      closeLabelPopover();
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);
    window.addEventListener('scroll', handleScroll, true);
    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
      window.removeEventListener('scroll', handleScroll, true);
    };
  }, [closeLabelPopover, labelPopoverState]);

  useEffect(() => {
    if (!messageContextMenu) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!messageContextMenuRef.current?.contains(event.target as Node)) {
        closeMessageContextMenu();
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeMessageContextMenu();
      }
    };
    const handleScroll = () => {
      closeMessageContextMenu();
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);
    window.addEventListener('scroll', handleScroll, true);
    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
      window.removeEventListener('scroll', handleScroll, true);
    };
  }, [closeMessageContextMenu, messageContextMenu]);

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

  return {
    labelPopoverState,
    labelPopoverDraft,
    messageContextMenu,
    labelPopoverRef,
    messageContextMenuRef,
    closeLabelPopover,
    closeMessageContextMenu,
    openLabelPopover,
    openMessageContextMenu,
    handleLabelDraftChange,
    handleLabelDraftCompositionStart,
    handleLabelDraftCompositionEnd,
  };
}