import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { type Dispatch, type SetStateAction, useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { toolsApi, type ToolConfig } from '@/api/modules/tools';
import type { ToolDraftMap } from '@/types/settings';
import { buildToolDraftSnapshot, serialize } from '@/utils/settings-helpers';

interface ToolLoadOptions { silent?: boolean; discardTool?: string; }
interface UseSettingsToolsReturn {
  tools: ToolConfig[];
  toolsLoading: boolean;
  toolsError: string | null;
  savedToolDrafts: ToolDraftMap;
  setSavedToolDrafts: Dispatch<SetStateAction<ToolDraftMap>>;
  draftToolDrafts: ToolDraftMap;
  setDraftToolDrafts: Dispatch<SetStateAction<ToolDraftMap>>;
  loadTools: (options?: ToolLoadOptions) => Promise<void>;
  handleToolDraftChange: (toolName: string, path: string, value: unknown) => void;
  handleToolEnabledChange: (toolName: string, enabled: boolean) => void;
}

export function useSettingsTools(): UseSettingsToolsReturn {
  const { t } = useTranslation('app');
  const requestIdRef = useRef(0);
  useEffect(() => () => { requestIdRef.current += 1; }, []);
  const [tools, setTools] = useState<ToolConfig[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [savedToolDrafts, setSavedToolDraftsState] = useState<ToolDraftMap>({});
  const savedRef = useRef<ToolDraftMap>({});
  const setSavedToolDrafts: Dispatch<SetStateAction<ToolDraftMap>> = useCallback((update) => {
    const next = typeof update === 'function' ? update(savedRef.current) : update;
    savedRef.current = next;
    setSavedToolDraftsState(next);
  }, []);
  const [draftToolDrafts, setDraftToolDraftsState] = useState<ToolDraftMap>({});
  const draftRef = useRef<ToolDraftMap>({});
  const setDraftToolDrafts: Dispatch<SetStateAction<ToolDraftMap>> = useCallback((update) => {
    const next = typeof update === 'function' ? update(draftRef.current) : update;
    draftRef.current = next;
    setDraftToolDraftsState(next);
  }, []);

  const currentDrafts = useRef({ tools, savedToolDrafts, draftToolDrafts });
  currentDrafts.current = { tools, savedToolDrafts, draftToolDrafts };

  const loadTools = useCallback(async ({ silent = false, discardTool }: ToolLoadOptions = {}) => {
    const requestId = ++requestIdRef.current;
    const savedAtStart = savedRef.current;
    const draftAtStart = discardTool ? serialize(draftRef.current[discardTool]) : null;
    if (!silent) {
      setToolsLoading(true);
      setToolsError(null);
    }
    try {
      const response = await toolsApi.listWithConfig();
      if (requestId !== requestIdRef.current) return;
      if (savedRef.current !== savedAtStart) return;
      setToolsError(null);
      const nextTools = response.tools;
      const nextDrafts = buildToolDraftSnapshot(nextTools);
      const current = { ...currentDrafts.current, savedToolDrafts: savedRef.current, draftToolDrafts: draftRef.current };
      const saved = { ...nextDrafts };
      const drafts = { ...nextDrafts };
      const visibleTools = [...nextTools];
      for (const [name, draft] of Object.entries(current.draftToolDrafts)) {
        if (name === discardTool && serialize(draft) === draftAtStart) continue;
        if (serialize(draft) === serialize(current.savedToolDrafts[name])) continue;
        drafts[name] = draft;
        if (current.savedToolDrafts[name]) saved[name] = current.savedToolDrafts[name];
        const previous = current.tools.find((tool) => tool.name === name);
        if (previous && !visibleTools.some((tool) => tool.name === name)) visibleTools.push(previous);
      }
      setTools(visibleTools);
      setSavedToolDrafts(saved);
      setDraftToolDrafts(drafts);
    } catch (error: unknown) {
      if (requestId !== requestIdRef.current) return;
      const message = error instanceof Error ? error.message : t('settings.errorUnknown');
      setToolsError(t('settings.loadToolsFailed', { message }));
      if (!silent) toast.error(t('settings.loadToolsFailed', { message }));
    } finally {
      if (requestId === requestIdRef.current) {
        setToolsLoading(false);
      }
    }
  }, [t, setDraftToolDrafts, setSavedToolDrafts]);

  useCenterRefresh(() => loadTools({ silent: true }), !toolsLoading);

  const handleToolDraftChange = useCallback((toolName: string, path: string, value: unknown) => {
    setDraftToolDrafts((prev) => ({
      ...prev,
      [toolName]: {
        revision: prev[toolName]?.revision ?? tools.find((tool) => tool.name === toolName)?.revision ?? '',
        enabled: prev[toolName]?.enabled ?? tools.find((tool) => tool.name === toolName)?.enabled ?? true,
        values: {
          ...(prev[toolName]?.values || {}),
          [path]: value,
        },
      },
    }));
  }, [tools, setDraftToolDrafts]);

  const handleToolEnabledChange = useCallback((toolName: string, enabled: boolean) => {
    setDraftToolDrafts((prev) => ({
      ...prev,
      [toolName]: {
        revision: prev[toolName]?.revision ?? tools.find((tool) => tool.name === toolName)?.revision ?? '',
        enabled,
        values: {
          ...(prev[toolName]?.values || tools.find((tool) => tool.name === toolName)?.current_values || {}),
        },
      },
    }));
  }, [tools, setDraftToolDrafts]);

  return {
    tools,
    toolsLoading,
    toolsError,
    savedToolDrafts,
    setSavedToolDrafts,
    draftToolDrafts,
    setDraftToolDrafts,
    loadTools,
    handleToolDraftChange,
    handleToolEnabledChange,
  };
}

export type { UseSettingsToolsReturn };
