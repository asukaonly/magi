import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { skillsApi, type SkillItem } from '@/api/modules/skills';
import type { ToolConfig } from '@/api/modules/tools';
import { DynamicToolsConfig } from '@/components/config-forms/DynamicToolConfig';
import { Switch } from '@/components/ui/switch';
import type { ToolDraftMap } from '@/types/settings';

function SettingsGroup({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div className="space-y-1.5">
        <h3 className="text-sm font-semibold tracking-[0.01em] text-foreground">{title}</h3>
        {description ? <p className="max-w-3xl text-xs leading-6 text-muted-foreground">{description}</p> : null}
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

interface SettingsToolsSectionProps {
  tools: ToolConfig[];
  toolsLoading: boolean;
  toolsError: string | null;
  draftToolDrafts: ToolDraftMap;
  selectedSkills: string[];
  onToolDraftChange: (toolName: string, path: string, value: unknown) => void;
  onToolEnabledChange: (toolName: string, enabled: boolean) => void;
  onSelectedSkillsChange: (skills: string[]) => void;
}

export function SettingsToolsSection({
  tools,
  toolsLoading,
  toolsError,
  draftToolDrafts,
  selectedSkills,
  onToolDraftChange,
  onToolEnabledChange,
  onSelectedSkillsChange,
}: SettingsToolsSectionProps) {
  const { t } = useTranslation('app');
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsError, setSkillsError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const loadSkills = async () => {
      setSkillsLoading(true);
      setSkillsError(null);
      try {
        const data = await skillsApi.list();
        if (!cancelled) {
          setSkills(Array.isArray(data) ? data : []);
        }
      } catch (error: unknown) {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : t('settings.errorUnknown');
          setSkillsError(message);
          setSkills([]);
        }
      } finally {
        if (!cancelled) {
          setSkillsLoading(false);
        }
      }
    };

    void loadSkills();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const skillsEnabled = selectedSkills.length > 0;

  return (
    <div className="space-y-8">
      <DynamicToolsConfig
        tools={tools}
        loading={toolsLoading}
        error={toolsError}
        drafts={draftToolDrafts}
        onUpdateConfig={onToolDraftChange}
        onUpdateEnabled={onToolEnabledChange}
      />

      <SettingsGroup
        title={t('tools.skills.label', { ns: 'onboarding' })}
        description={
          skills.length > 0
            ? t('tools.skills.desc', { ns: 'onboarding', count: skills.length })
            : t('tools.skills.empty', { ns: 'onboarding' })
        }
      >
        <label className="grid gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
          <div className="space-y-1">
            <div className="text-sm font-medium text-foreground">{t('tools.skills.enable', { ns: 'onboarding' })}</div>
            <div className="text-xs leading-6 text-muted-foreground">
              {t('tools.skills.emptyHint', { ns: 'onboarding' })}
            </div>
          </div>
          <div className="flex justify-start sm:justify-end">
            <Switch
              checked={skillsEnabled}
              disabled={skills.length === 0}
              onCheckedChange={(checked) => onSelectedSkillsChange(checked ? skills.map((skill) => skill.name) : [])}
            />
          </div>
        </label>

        <div className="max-h-64 overflow-auto">
          {skillsLoading ? (
            <div className="py-3 text-xs text-muted-foreground">{t('settings.loadingTools')}</div>
          ) : null}

          {!skillsLoading && skillsError ? (
            <div className="py-3 text-xs text-destructive">{skillsError}</div>
          ) : null}

          {!skillsLoading && !skillsError && skills.length > 0
            ? skills.map((skill) => {
                const checked = selectedSkills.includes(skill.name);
                return (
                  <label
                    key={skill.name}
                    className="flex items-center justify-between gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 last:border-b-0"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{skill.name}</div>
                      <div className="truncate text-xs text-muted-foreground">{skill.description}</div>
                    </div>
                    <Switch
                      checked={checked}
                      onCheckedChange={(nextChecked) => {
                        const nextSkills = new Set(selectedSkills);
                        if (nextChecked) {
                          nextSkills.add(skill.name);
                        } else {
                          nextSkills.delete(skill.name);
                        }
                        onSelectedSkillsChange(Array.from(nextSkills));
                      }}
                    />
                  </label>
                );
              })
            : null}

          {!skillsLoading && !skillsError && skills.length === 0 ? (
            <div className="py-3 text-xs text-muted-foreground">{t('tools.skills.emptyHint', { ns: 'onboarding' })}</div>
          ) : null}
        </div>
      </SettingsGroup>
    </div>
  );
}