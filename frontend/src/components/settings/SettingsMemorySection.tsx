import type { SystemConfig } from '@/api/modules/config';
import {
  MemoryDataSettingsSection,
  MemoryEventsSettingsSection,
  MemoryGeneralSettingsSection,
  MemoryKnowledgeSettingsSection,
  MemoryReflectionSettingsSection,
  MemorySkillsSettingsSection,
  MemoryWorkbenchSettingsSection,
} from '@/components/settings';
import type { MemoryToggleFieldId } from '@/types/settings';

type SettingsMemorySectionId =
  | 'memoryGeneral'
  | 'memoryData'
  | 'memoryWorkbench'
  | 'memoryEvents'
  | 'memoryKnowledge'
  | 'memoryReflection'
  | 'memorySkills';

interface SettingsMemorySectionProps {
  section: SettingsMemorySectionId;
  draftConfig: SystemConfig;
  patchDraftConfig: (updater: (draft: SystemConfig) => void) => void;
  updateMemoryToggle: (field: MemoryToggleFieldId, checked: boolean) => void;
  hasEmbeddingModel: boolean;
  hasCrossEncoderModel: boolean;
}


export function SettingsMemorySection({
  section,
  draftConfig,
  patchDraftConfig,
  updateMemoryToggle,
  hasEmbeddingModel,
  hasCrossEncoderModel,
}: SettingsMemorySectionProps) {
  switch (section) {
    case 'memoryGeneral':
      return (
        <MemoryGeneralSettingsSection
          draftConfig={draftConfig}
          patchDraftConfig={patchDraftConfig}
          hasCrossEncoderModel={hasCrossEncoderModel}
        />
      );

    case 'memoryData':
      return <MemoryDataSettingsSection />;

    case 'memoryWorkbench':
      return (
        <MemoryWorkbenchSettingsSection
          draftConfig={draftConfig}
          patchDraftConfig={patchDraftConfig}
          updateMemoryToggle={updateMemoryToggle}
        />
      );

    case 'memoryEvents':
      return (
        <MemoryEventsSettingsSection
          draftConfig={draftConfig}
          patchDraftConfig={patchDraftConfig}
          updateMemoryToggle={updateMemoryToggle}
          hasEmbeddingModel={hasEmbeddingModel}
        />
      );

    case 'memoryKnowledge':
      return (
        <MemoryKnowledgeSettingsSection
          draftConfig={draftConfig}
          patchDraftConfig={patchDraftConfig}
          updateMemoryToggle={updateMemoryToggle}
          hasEmbeddingModel={hasEmbeddingModel}
        />
      );

    case 'memoryReflection':
      return (
        <MemoryReflectionSettingsSection
          draftConfig={draftConfig}
          patchDraftConfig={patchDraftConfig}
          updateMemoryToggle={updateMemoryToggle}
          hasEmbeddingModel={hasEmbeddingModel}
        />
      );

    case 'memorySkills':
      return (
        <MemorySkillsSettingsSection
          draftConfig={draftConfig}
          patchDraftConfig={patchDraftConfig}
          updateMemoryToggle={updateMemoryToggle}
        />
      );
  }
}

export type { SettingsMemorySectionId };
