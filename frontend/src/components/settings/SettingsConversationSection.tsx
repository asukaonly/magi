import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FolderOpen, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';

import { DEFAULT_SYSTEM_CONFIG, type SystemConfig } from '@/api/modules/config';
import type { ControlSettingsDTO } from '@/api/modules/control';
import { ControlSettingsPanel } from '@/components/control';
import { SettingsGroup, SettingsSectionShell, SettingsSwitchRow } from '@/components/settings/SettingsSectionPrimitives';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { pickDirectory } from '@/runtime/desktop';

interface SettingsConversationSectionProps {
  draftConfig: SystemConfig;
  draftControlSettings: ControlSettingsDTO | null;
  patchDraftConfig: (updater: (draft: SystemConfig) => void) => void;
  patchDraftControlSettings: (updater: (draft: ControlSettingsDTO) => void) => void;
}

export function SettingsConversationSection({
  draftConfig,
  draftControlSettings,
  patchDraftConfig,
  patchDraftControlSettings,
}: SettingsConversationSectionProps) {
  const { t } = useTranslation('app');
  const [pickingWorkspace, setPickingWorkspace] = useState(false);
  const defaultChatWorkspaceFallback = DEFAULT_SYSTEM_CONFIG.preferences.default_chat_workspace_path;
  const coreModelSupportsVision = Boolean(draftConfig.llm?.selections?.core?.capabilities?.vision);
  const mediaGroundingEnabled = Boolean(draftConfig.preferences.allow_media_grounding_for_conversation);
  const mediaGroundingSwitchDisabled = !coreModelSupportsVision && !mediaGroundingEnabled;
  const defaultChatWorkspacePath = draftConfig.preferences.default_chat_workspace_path;
  const effectiveDefaultChatWorkspacePath = defaultChatWorkspacePath ?? defaultChatWorkspaceFallback ?? '';
  const canRestoreDefaultChatWorkspace = defaultChatWorkspacePath !== defaultChatWorkspaceFallback;
  const rhythmMode = draftConfig.preferences.conversation_rhythm_mode ?? 'off';
  const conversationRhythmEnabled = Boolean(draftConfig.preferences.conversation_rhythm_enabled)
    && (rhythmMode === 'natural' || rhythmMode === 'expressive');

  const handlePickWorkspace = async () => {
    setPickingWorkspace(true);
    try {
      const selectedPath = await pickDirectory(effectiveDefaultChatWorkspacePath);
      if (!selectedPath) {
        return;
      }
      patchDraftConfig((draft) => {
        draft.preferences.default_chat_workspace_path = selectedPath;
      });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'unknown';
      toast.error(t('settings.defaultChatWorkspacePickFailed', { message }));
    } finally {
      setPickingWorkspace(false);
    }
  };

  return (
    <SettingsSectionShell>
      <SettingsGroup
        title={t('settings.fields.defaultChatWorkspace')}
        description={t('settings.defaultChatWorkspaceDesc')}
        contentClassName="space-y-0"
      >
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <label className="min-w-0 flex-1" htmlFor="default-chat-workspace">
            <Input
              id="default-chat-workspace"
              aria-label={t('settings.fields.defaultChatWorkspace')}
              readOnly
              value={effectiveDefaultChatWorkspacePath}
              placeholder={t('settings.defaultChatWorkspacePlaceholder')}
            />
          </label>
          <div className="flex flex-wrap gap-2 sm:flex-none">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                void handlePickWorkspace();
              }}
              disabled={pickingWorkspace}
            >
              <FolderOpen className="mr-2 h-4 w-4" />
              {t('settings.actions.chooseDirectory')}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => patchDraftConfig((draft) => {
                draft.preferences.default_chat_workspace_path = defaultChatWorkspaceFallback;
              })}
              disabled={!canRestoreDefaultChatWorkspace}
            >
              <RotateCcw className="mr-2 h-4 w-4" />
              {t('settings.actions.restoreDefaultDirectory')}
            </Button>
          </div>
        </div>
      </SettingsGroup>

      <SettingsSwitchRow
        title={t('settings.streamingChatLabel')}
        description={t('settings.streamingChatDesc')}
        ariaLabel={t('settings.fields.streamingChat')}
        checked={draftConfig.preferences.streaming_chat_enabled}
        onCheckedChange={(checked) => patchDraftConfig((draft) => {
          draft.preferences.streaming_chat_enabled = checked;
          if (checked) {
            draft.preferences.conversation_rhythm_enabled = false;
            draft.preferences.conversation_rhythm_mode = 'off';
          }
        })}
      />

      <SettingsSwitchRow
        title={t('settings.conversationRhythmLabel')}
        description={t('settings.conversationRhythmDesc')}
        ariaLabel={t('settings.fields.conversationRhythm')}
        checked={conversationRhythmEnabled}
        onCheckedChange={(checked) => patchDraftConfig((draft) => {
          draft.preferences.conversation_rhythm_enabled = checked;
          draft.preferences.conversation_rhythm_mode = checked
            ? (draft.preferences.conversation_rhythm_mode === 'expressive' ? 'expressive' : 'natural')
            : 'off';
          if (checked) {
            draft.preferences.streaming_chat_enabled = false;
          }
        })}
      />

      <SettingsSwitchRow
        title={t('settings.mediaGroundingLabel')}
        description={t('settings.mediaGroundingDesc')}
        hint={!coreModelSupportsVision ? t('settings.mediaGroundingUnavailable') : undefined}
        hintClassName={!coreModelSupportsVision ? 'text-amber-600 dark:text-amber-300' : undefined}
        ariaLabel={t('settings.fields.mediaGrounding')}
        checked={draftConfig.preferences.allow_media_grounding_for_conversation}
        disabled={mediaGroundingSwitchDisabled}
        onCheckedChange={(checked) => patchDraftConfig((draft) => {
          draft.preferences.allow_media_grounding_for_conversation = checked;
        })}
      />

      <SettingsSwitchRow
        title={t('settings.allowInterjectionLabel')}
        description={t('settings.allowInterjectionDesc')}
        ariaLabel={t('settings.fields.allowInterjection')}
        checked={draftConfig.preferences.allow_interjection}
        onCheckedChange={(checked) => patchDraftConfig((draft) => {
          draft.preferences.allow_interjection = checked;
        })}
      />

      <SettingsSwitchRow
        title={t('settings.allowAskInBackgroundLabel')}
        description={t('settings.allowAskInBackgroundDesc')}
        ariaLabel={t('settings.fields.allowAskInBackground')}
        checked={draftConfig.preferences.allow_ask_in_background}
        onCheckedChange={(checked) => patchDraftConfig((draft) => {
          draft.preferences.allow_ask_in_background = checked;
        })}
      />

      {draftControlSettings ? (
        <ControlSettingsPanel
          value={draftControlSettings}
          onChange={(next) => patchDraftControlSettings((draft) => {
            draft.permission_mode = next.permission_mode;
            draft.plan_approval_required = next.plan_approval_required;
          })}
        />
      ) : null}
    </SettingsSectionShell>
  );
}
