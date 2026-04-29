import { type Dispatch, type SetStateAction, useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { toolsApi, type ToolConfig } from '@/api/modules/tools';
import type { ToolDraftMap } from '@/types/settings';
import { buildToolDraftSnapshot } from '@/utils/settings-helpers';

interface UseSettingsToolsReturn {
  tools: ToolConfig[];
  toolsLoading: boolean;
  toolsError: string | null;
  savedToolDrafts: ToolDraftMap;
  setSavedToolDrafts: Dispatch<SetStateAction<ToolDraftMap>>;
  draftToolDrafts: ToolDraftMap;
  setDraftToolDrafts: Dispatch<SetStateAction<ToolDraftMap>>;
  loadTools: (options?: { silent?: boolean }) => Promise<void>;
  handleToolDraftChange: (toolName: string, path: string, value: unknown) => void;
  handleToolEnabledChange: (toolName: string, enabled: boolean) => void;
}

export function useSettingsTools(): UseSettingsToolsReturn {
  const { t } = useTranslation('app');
  const [tools, setTools] = useState<ToolConfig[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [savedToolDrafts, setSavedToolDrafts] = useState<ToolDraftMap>({});
  const [draftToolDrafts, setDraftToolDrafts] = useState<ToolDraftMap>({});

  const loadTools = useCallback(async ({ silent = false }: { silent?: boolean } = {}) => {
    if (!silent) {
      setToolsLoading(true);
      setToolsError(null);
    }
    try {
      const response = await toolsApi.listWithConfig();
      const nextTools = response.tools || [];
      const nextDrafts = buildToolDraftSnapshot(nextTools);
      setTools(nextTools);
      setSavedToolDrafts(nextDrafts);
      setDraftToolDrafts((prev) => {
        if (Object.keys(prev).length === 0) {
          return nextDrafts;
        }
        const merged = structuredClone(prev);
        for (const [toolName, snapshot] of Object.entries(nextDrafts)) {
          merged[toolName] = {
            enabled: merged[toolName]?.enabled ?? snapshot.enabled,
            values: {
              ...snapshot.values,
              ...(merged[toolName]?.values || {}),
            },
          };
        }
        return merged;
      });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : t('settings.errorUnknown');
      setToolsError(t('settings.loadToolsFailed', { message }));
      toast.error(t('settings.loadToolsFailed', { message }));
    } finally {
      if (!silent) {
        setToolsLoading(false);
      }
    }
  }, [t]);

  const handleToolDraftChange = useCallback((toolName: string, path: string, value: unknown) => {
    setDraftToolDrafts((prev) => ({
      ...prev,
      [toolName]: {
        enabled: prev[toolName]?.enabled ?? tools.find((tool) => tool.name === toolName)?.enabled ?? true,
        values: {
          ...(prev[toolName]?.values || {}),
          [path]: value,
        },
      },
    }));
  }, [tools]);

  const handleToolEnabledChange = useCallback((toolName: string, enabled: boolean) => {
    setDraftToolDrafts((prev) => ({
      ...prev,
      [toolName]: {
        enabled,
        values: {
          ...(prev[toolName]?.values || tools.find((tool) => tool.name === toolName)?.current_values || {}),
        },
      },
    }));
  }, [tools]);

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
