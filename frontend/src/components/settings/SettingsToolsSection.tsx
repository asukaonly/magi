import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { skillsApi, type SkillItem } from '@/api/modules/skills';
import type { ToolConfig } from '@/api/modules/tools';
import { DynamicToolsConfig } from '@/components/config-forms/DynamicToolConfig';
import { Switch } from '@/components/ui/switch';
import type { ToolDraftMap } from '@/types/settings';

type SettingsToolsView = 'builtin' | 'plugins' | 'skills';

interface SettingsToolsSectionProps {
  view: SettingsToolsView;
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
  view,
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

  const visibleTools = useMemo(() => {
    if (view === 'builtin') {
      return tools.filter((tool) => tool.category !== 'external');
    }
    if (view === 'plugins') {
      return tools.filter((tool) => tool.category === 'external');
    }
    return [];
  }, [tools, view]);

  useEffect(() => {
    if (view !== 'skills') {
      setSkills([]);
      setSkillsError(null);
      setSkillsLoading(false);
      return;
    }

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
  }, [t, view]);

  if (view !== 'skills') {
    const emptyMessage = view === 'plugins'
      ? t('settings.toolsEmptyPlugins')
      : t('settings.toolsEmptyBuiltin');
    const description = view === 'plugins'
      ? t('settings.toolsPluginsDesc')
      : t('settings.toolsBuiltinDesc');

    return (
      <div className="space-y-6">
        <p className="text-sm leading-6 text-muted-foreground">{description}</p>
        {visibleTools.length > 0 ? (
          <DynamicToolsConfig
            tools={visibleTools}
            loading={toolsLoading}
            error={toolsError}
            drafts={draftToolDrafts}
            onUpdateConfig={onToolDraftChange}
            onUpdateEnabled={onToolEnabledChange}
          />
        ) : toolsLoading ? (
          <div className="py-3 text-sm text-muted-foreground">{t('settings.loadingTools')}</div>
        ) : toolsError ? (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
            {toolsError}
          </div>
        ) : (
          <div className="rounded-lg border border-[hsl(var(--settings-subnav-border)/0.6)] bg-[hsl(var(--settings-shell-elevated)/0.28)] px-4 py-3 text-sm text-muted-foreground">
            {emptyMessage}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <section className="flex min-h-0 flex-1 flex-col">
        <div className="shrink-0 space-y-1.5 pb-4">
          <h3 className="text-sm font-semibold tracking-[0.01em] text-foreground">
            {t('tools.skills.label', { ns: 'onboarding' })}
          </h3>
          <p className="max-w-3xl text-xs leading-6 text-muted-foreground">
            {skills.length > 0
              ? t('tools.skills.desc', { ns: 'onboarding', count: skills.length })
              : t('tools.skills.empty', { ns: 'onboarding' })}
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto border-t border-[hsl(var(--settings-subnav-border)/0.6)] pr-2">
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
            <div className="py-3 text-xs text-muted-foreground">{t('tools.skills.empty', { ns: 'onboarding' })}</div>
          ) : null}
        </div>
      </section>
    </div>
  );
}