import { useTranslation } from 'react-i18next';

import type { SystemConfig } from '@/api/modules/config';
import { LabeledSelectField, NumberField } from '@/components/settings/form-fields';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import type { MemoryToggleFieldId } from '@/types/settings';

interface MemorySettingsSectionProps {
  draftConfig: SystemConfig;
  patchDraftConfig: (updater: (draft: SystemConfig) => void) => void;
  updateMemoryToggle: (field: MemoryToggleFieldId, checked: boolean) => void;
  hasEmbeddingModel: boolean;
}

function MemorySectionShell({
  children,
}: {
  children: React.ReactNode;
}) {
  return <div className="space-y-8">{children}</div>;
}

function MemoryGroup({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4 border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-6">
      <div className="space-y-1.5">
        <h3 className="text-sm font-semibold tracking-[0.01em] text-foreground">{title}</h3>
        {description ? <p className="max-w-3xl text-xs leading-6 text-muted-foreground">{description}</p> : null}
      </div>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function MemorySwitchRow({
  label,
  description,
  checked,
  onCheckedChange,
  disabled = false,
}: {
  label: string;
  description: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="grid gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
      <div className="space-y-1">
        <div className="text-sm font-medium text-foreground">{label}</div>
        <div className="text-xs leading-6 text-muted-foreground">{description}</div>
      </div>
      <div className="flex justify-start sm:justify-end">
        <Switch checked={checked} disabled={disabled} onCheckedChange={onCheckedChange} aria-label={label} />
      </div>
    </label>
  );
}

function MemoryMetricRow({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 last:border-b-0">
      <div className="text-xs tracking-[0.02em] text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-medium text-foreground">{value}</div>
      {hint ? <div className="mt-1 text-xs leading-6 text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

function DependencyNotice({
  title,
  description,
  cta,
  onRestore,
}: {
  title: string;
  description: string;
  cta: string;
  onRestore: () => void;
}) {
  return (
    <div className="border-l-2 border-[hsl(var(--settings-nav-active)/0.52)] pl-4">
      <div className="text-sm font-semibold text-foreground">{title}</div>
      <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p>
      <Button type="button" variant="ghost" size="sm" className="mt-2 h-8 px-0 text-sm" onClick={onRestore}>
        {cta}
      </Button>
    </div>
  );
}

export function MemoryGeneralSettingsSection({
  draftConfig,
  patchDraftConfig,
  hasEmbeddingModel,
}: Omit<MemorySettingsSectionProps, 'updateMemoryToggle'>) {
  const { t } = useTranslation('app');
  const embeddingSelection = draftConfig.llm?.selections?.embedding;

  return (
    <MemorySectionShell>
      <div className="grid gap-8 xl:grid-cols-[minmax(0,1.4fr)_minmax(280px,0.8fr)]">
        <MemoryGroup
          title={t('settings.memory.sections.general.pipelineTitle')}
          description={t('settings.memory.sections.general.pipelineDescription')}
        >
          <MemorySwitchRow
            label={t('settings.memory.fields.async_embeddings.label')}
            description={t('settings.memory.fields.async_embeddings.description')}
            checked={draftConfig.memory.async_embeddings}
            onCheckedChange={(checked) => patchDraftConfig((draft) => {
              draft.memory.async_embeddings = checked;
            })}
          />

          <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
            <LabeledSelectField
              label={t('settings.memory.fields.embedding_backend.label')}
              value={draftConfig.memory.embedding.backend}
              options={[
                { label: 'sqlite-vec', value: 'sqlite_vec' },
                { label: 'OpenAI API', value: 'openai' },
              ]}
              onChange={(value) => patchDraftConfig((draft) => {
                draft.memory.embedding.backend = value as SystemConfig['memory']['embedding']['backend'];
              })}
            />
            <p className="mt-2 text-xs leading-6 text-muted-foreground">
              {t('settings.memory.fields.embedding_backend.description')}
            </p>
          </div>
        </MemoryGroup>

        <MemoryGroup
          title={t('settings.memory.sections.general.embeddingModelTitle')}
          description={t('settings.memory.sections.general.embeddingModelDescription')}
        >
          {hasEmbeddingModel ? (
            <div>
              <MemoryMetricRow
                label={t('settings.fields.provider')}
                value={embeddingSelection.provider_id || '-'}
              />
              <MemoryMetricRow
                label={t('settings.fields.model')}
                value={embeddingSelection.model || '-'}
              />
              <MemoryMetricRow
                label={t('settings.memory.fields.embedding_backend.label')}
                value={embeddingSelection.embedding_dimension ? `${embeddingSelection.embedding_dimension}d` : '-'}
              />
            </div>
          ) : (
            <div className="text-sm leading-7 text-muted-foreground">
              {t('settings.memory.sections.general.embeddingModelEmpty')}
            </div>
          )}
        </MemoryGroup>
      </div>
    </MemorySectionShell>
  );
}

export function MemoryWorkbenchSettingsSection({
  draftConfig,
  patchDraftConfig,
  updateMemoryToggle,
}: Pick<MemorySettingsSectionProps, 'draftConfig' | 'patchDraftConfig' | 'updateMemoryToggle'>) {
  const { t } = useTranslation('app');

  return (
    <MemorySectionShell>
      <MemoryGroup
        title={t('settings.memory.fields.enable_l0.label')}
        description={t('settings.memory.fields.enable_l0.description')}
      >
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l0.label')}
          description={t('settings.memory.fields.enable_l0.description')}
          checked={draftConfig.memory.l0.enabled}
          onCheckedChange={(checked) => updateMemoryToggle('l0', checked)}
        />
        <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
          <NumberField
            label={t('settings.memory.fields.l0_checkpoint_interval_seconds.label')}
            value={draftConfig.memory.l0.checkpoint_interval_seconds}
            min={1}
            onChange={(value) => patchDraftConfig((draft) => {
              draft.memory.l0.checkpoint_interval_seconds = value;
            })}
          />
        </div>
        <MemorySwitchRow
          label={t('settings.memory.fields.runtime_replay_include_l0_only.label')}
          description={t('settings.memory.fields.runtime_replay_include_l0_only.description')}
          checked={draftConfig.memory.l0.runtime_replay_include_l0_only ?? false}
          disabled={!draftConfig.memory.l0.enabled}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l0.runtime_replay_include_l0_only = checked;
          })}
        />
      </MemoryGroup>
    </MemorySectionShell>
  );
}

export function MemoryEventsSettingsSection({
  draftConfig,
  patchDraftConfig,
  updateMemoryToggle,
  hasEmbeddingModel,
}: MemorySettingsSectionProps) {
  const { t } = useTranslation('app');

  return (
    <MemorySectionShell>
      <MemoryGroup
        title={t('settings.memory.fields.enable_l1.label')}
        description={t('settings.memory.fields.enable_l1.description')}
      >
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l1.label')}
          description={t('settings.memory.fields.enable_l1.description')}
          checked={draftConfig.memory.l1.enabled}
          onCheckedChange={(checked) => updateMemoryToggle('l1', checked)}
        />
        <div className="grid gap-6 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 lg:grid-cols-2">
          <NumberField
            label={t('settings.memory.fields.retention_days.label')}
            value={draftConfig.memory.l1.retention_days}
            min={1}
            onChange={(value) => patchDraftConfig((draft) => {
              draft.memory.l1.retention_days = value;
            })}
          />
        </div>
      </MemoryGroup>

      <MemoryGroup
        title={t('settings.memory.sections.events.retrievalTitle')}
        description={t('settings.memory.sections.events.retrievalDescription')}
      >
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_t1_importance.label')}
          description={t('settings.memory.fields.enable_t1_importance.description')}
          checked={draftConfig.memory.l1.t1_importance_enabled ?? false}
          disabled={!draftConfig.memory.l1.enabled}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l1.t1_importance_enabled = checked;
          })}
        />
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l1_vectorization.label')}
          description={
            hasEmbeddingModel
              ? t('settings.memory.fields.enable_l1_vectorization.description')
              : t('settings.memory.fields.enable_l1_vectorization.description_disabled')
          }
          checked={draftConfig.memory.l1.vectors_enabled ?? false}
          disabled={!draftConfig.memory.l1.enabled || !hasEmbeddingModel}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l1.vectors_enabled = checked;
          })}
        />
      </MemoryGroup>
    </MemorySectionShell>
  );
}

export function MemoryKnowledgeSettingsSection({
  draftConfig,
  patchDraftConfig,
  updateMemoryToggle,
}: Pick<MemorySettingsSectionProps, 'draftConfig' | 'patchDraftConfig' | 'updateMemoryToggle'>) {
  const { t } = useTranslation('app');

  return (
    <MemorySectionShell>
      {!draftConfig.memory.l1.enabled ? (
        <DependencyNotice
          title={t('settings.memory.form.l1DependencyTitle')}
          description={t('settings.memory.form.l1DependencyDescription')}
          cta={t('settings.memory.form.restoreL1')}
          onRestore={() => updateMemoryToggle('l1', true)}
        />
      ) : null}

      <MemoryGroup
        title={t('settings.memory.sections.knowledge.extractionTitle')}
        description={t('settings.memory.sections.knowledge.extractionDescription')}
      >
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l2.label')}
          description={t('settings.memory.fields.enable_l2.description')}
          checked={draftConfig.memory.l2.enabled}
          disabled={!draftConfig.memory.l1.enabled}
          onCheckedChange={(checked) => updateMemoryToggle('l2', checked)}
        />
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l2_llm_extraction.label')}
          description={t('settings.memory.fields.enable_l2_llm_extraction.description')}
          checked={draftConfig.memory.l2.llm_extraction_enabled ?? false}
          disabled={!draftConfig.memory.l2.enabled}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l2.llm_extraction_enabled = checked;
          })}
        />
      </MemoryGroup>

      <MemoryGroup
        title={t('settings.memory.sections.knowledge.flushTitle')}
        description={t('settings.memory.sections.knowledge.flushDescription')}
      >
        <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
          <NumberField
            label={t('settings.memory.fields.l2_batch_flush_interval_seconds.label')}
            value={draftConfig.memory.l2.batch_flush_interval_seconds}
            min={30}
            onChange={(value) => patchDraftConfig((draft) => {
              draft.memory.l2.batch_flush_interval_seconds = value;
            })}
          />
          <p className="mt-2 text-xs leading-6 text-muted-foreground">
            {t('settings.memory.fields.l2_batch_flush_interval_seconds.description')}
          </p>
        </div>
      </MemoryGroup>

      <MemoryGroup
        title={t('settings.memory.sections.knowledge.arbitrationTitle')}
        description={t('settings.memory.sections.knowledge.arbitrationDescription')}
      >
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l2_conflict_arbitration.label')}
          description={t('settings.memory.fields.enable_l2_conflict_arbitration.description')}
          checked={draftConfig.memory.l2.conflict_arbitration_enabled ?? true}
          disabled={!draftConfig.memory.l2.enabled}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l2.conflict_arbitration_enabled = checked;
          })}
        />
        <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
          <NumberField
            label={t('settings.memory.fields.l2_conflict_arbitration_min_confidence.label')}
            value={draftConfig.memory.l2.conflict_arbitration_min_confidence}
            min={0}
            max={1}
            step={0.05}
            onChange={(value) => patchDraftConfig((draft) => {
              draft.memory.l2.conflict_arbitration_min_confidence = value;
            })}
          />
          <p className="mt-2 text-xs leading-6 text-muted-foreground">
            {t('settings.memory.fields.l2_conflict_arbitration_min_confidence.description')}
          </p>
        </div>
      </MemoryGroup>
    </MemorySectionShell>
  );
}

export function MemoryReflectionSettingsSection({
  draftConfig,
  patchDraftConfig,
  updateMemoryToggle,
  hasEmbeddingModel,
}: MemorySettingsSectionProps) {
  const { t } = useTranslation('app');

  return (
    <MemorySectionShell>
      {!draftConfig.memory.l1.enabled ? (
        <DependencyNotice
          title={t('settings.memory.form.l1DependencyTitle')}
          description={t('settings.memory.form.l1DependencyDescription')}
          cta={t('settings.memory.form.restoreL1')}
          onRestore={() => updateMemoryToggle('l1', true)}
        />
      ) : null}

      <MemoryGroup
        title={t('settings.memory.fields.enable_l3.label')}
        description={t('settings.memory.fields.enable_l3.description')}
      >
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l3.label')}
          description={t('settings.memory.fields.enable_l3.description')}
          checked={draftConfig.memory.l3.enabled}
          disabled={!draftConfig.memory.l1.enabled}
          onCheckedChange={(checked) => updateMemoryToggle('l3', checked)}
        />
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l3_llm_summary.label')}
          description={t('settings.memory.fields.enable_l3_llm_summary.description')}
          checked={draftConfig.memory.l3.llm_summary_enabled ?? false}
          disabled={!draftConfig.memory.l3.enabled}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l3.llm_summary_enabled = checked;
          })}
        />
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l3_vectorization.label')}
          description={
            hasEmbeddingModel
              ? t('settings.memory.fields.enable_l3_vectorization.description')
              : t('settings.memory.fields.enable_l3_vectorization.description_disabled')
          }
          checked={draftConfig.memory.l3.vectors_enabled ?? false}
          disabled={!draftConfig.memory.l3.enabled || !hasEmbeddingModel}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l3.vectors_enabled = checked;
          })}
        />
      </MemoryGroup>
    </MemorySectionShell>
  );
}

export function MemorySkillsSettingsSection({
  draftConfig,
  patchDraftConfig,
  updateMemoryToggle,
}: Pick<MemorySettingsSectionProps, 'draftConfig' | 'patchDraftConfig' | 'updateMemoryToggle'>) {
  const { t } = useTranslation('app');

  return (
    <MemorySectionShell>
      {!draftConfig.memory.l1.enabled ? (
        <DependencyNotice
          title={t('settings.memory.form.l1DependencyTitle')}
          description={t('settings.memory.form.l1DependencyDescription')}
          cta={t('settings.memory.form.restoreL1')}
          onRestore={() => updateMemoryToggle('l1', true)}
        />
      ) : null}

      <MemoryGroup
        title={t('settings.memory.fields.enable_l4.label')}
        description={t('settings.memory.fields.enable_l4.description')}
      >
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l4.label')}
          description={t('settings.memory.fields.enable_l4.description')}
          checked={draftConfig.memory.l4.enabled}
          disabled={!draftConfig.memory.l1.enabled}
          onCheckedChange={(checked) => updateMemoryToggle('l4', checked)}
        />
        <MemorySwitchRow
          label={t('settings.memory.fields.enable_l4_skill_extraction.label')}
          description={t('settings.memory.fields.enable_l4_skill_extraction.description')}
          checked={draftConfig.memory.l4.skill_extraction_enabled ?? false}
          disabled={!draftConfig.memory.l4.enabled}
          onCheckedChange={(checked) => patchDraftConfig((draft) => {
            draft.memory.l4.skill_extraction_enabled = checked;
          })}
        />
      </MemoryGroup>
    </MemorySectionShell>
  );
}
