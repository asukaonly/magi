import { type Dispatch, type SetStateAction, useCallback, useMemo, useState } from 'react';
import { useChatShellStore } from '@/stores/chat-shell';

interface UseSettingsNavigationReturn {
  activeSection: string;
  setActiveSection: Dispatch<SetStateAction<string>>;
  expandedGroups: Record<string, boolean>;
  getGroupExpanded: (groupId: string) => boolean;
  setGroupExpanded: (groupId: string, expanded: boolean) => void;
  handleNavItemClick: (itemId: string, isGroup: boolean, firstChildId?: string) => void;
  usesInnerPaneScroll: boolean;
  timelineSelection: string | null;
  setTimelineSelection: Dispatch<SetStateAction<string | null>>;
  channelsSelection: string | null;
  setChannelsSelection: Dispatch<SetStateAction<string | null>>;
}

export function useSettingsNavigation(): UseSettingsNavigationReturn {
  const initialSearchParams = useMemo(() => new URLSearchParams(window.location.search), []);
  const settingsNavigationIntent = useChatShellStore((state) => state.settingsNavigationIntent);
  const [activeSection, setActiveSection] = useState(
    settingsNavigationIntent?.section || initialSearchParams.get('section') || 'preferences'
  );
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    llm: false,
    personality: false,
    memory: false,
    plugins: false,
    timeline: false,
    channels: false,
    tools: false,
  });
  const [timelineSelection, setTimelineSelection] = useState<string | null>(
    settingsNavigationIntent?.source || initialSearchParams.get('source')
  );
  const [channelsSelection, setChannelsSelection] = useState<string | null>(null);

  const usesInnerPaneScroll = useMemo(
    () => activeSection === 'llmProviders' || activeSection === 'toolsSkills',
    [activeSection]
  );

  const getGroupExpanded = useCallback(
    (groupId: string) => expandedGroups[groupId] ?? false,
    [expandedGroups]
  );

  const setGroupExpanded = useCallback((groupId: string, expanded: boolean) => {
    setExpandedGroups((prev) => ({ ...prev, [groupId]: expanded }));
  }, []);

  const handleNavItemClick = useCallback(
    (itemId: string, isGroup: boolean, firstChildId?: string) => {
      if (isGroup) {
        const isExpanded = getGroupExpanded(itemId);
        if (isExpanded) {
          setGroupExpanded(itemId, false);
          return;
        }
        setGroupExpanded(itemId, true);
        setActiveSection(firstChildId || itemId);
        return;
      }
      setActiveSection(itemId);
      if (itemId === 'timeline') {
        setTimelineSelection(null);
      }
      if (itemId === 'channels') {
        setChannelsSelection(null);
      }
    },
    [getGroupExpanded, setGroupExpanded]
  );

  return {
    activeSection,
    setActiveSection,
    expandedGroups,
    getGroupExpanded,
    setGroupExpanded,
    handleNavItemClick,
    usesInnerPaneScroll,
    timelineSelection,
    setTimelineSelection,
    channelsSelection,
    setChannelsSelection,
  };
}

export type { UseSettingsNavigationReturn };
