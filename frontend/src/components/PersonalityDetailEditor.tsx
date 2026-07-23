import React from 'react';
import { CircleHelp, Info, Plus, Trash2, Upload } from 'lucide-react';
import { AutoResizeTextarea } from '@/components/ui/auto-resize-textarea';
import { Button } from '@/components/ui/button';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import type {
  LayerModifierKey,
  LayerModifiers,
  PersonaLayerItem,
  PersonaRegister,
  PersonalityConfig,
  QuietHour,
  SignatureTrigger,
} from '@/api/modules/personas';

interface PersonalityDetailEditorProps {
  config: PersonalityConfig;
  patch: (fn: (draft: PersonalityConfig) => void) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
  onAvatarUpload?: (event: React.ChangeEvent<HTMLInputElement>) => void;
  uploadingAvatar?: boolean;
  avatarFilename?: string;
}

type MappingEntry = { key: string; value: string };
type LayerModifierValue = string | number | string[] | Record<string, number> | undefined;
type StructuredLayerModifierKey = Exclude<LayerModifierKey, 'behavior_shifts'>;
type LayerModifierEntry = { key: StructuredLayerModifierKey | ''; value: LayerModifierValue };

const REGISTER_KEYS = ['chat', 'analysis', 'task', 'emotional', 'crisis'] as const;
const SURFACE_LAYER_ID = 'surface';
const LAYER_MODIFIER_KEY_OPTIONS: readonly StructuredLayerModifierKey[] = [
  'memory_behavior',
  'protective_bias',
  'voice_unlocks',
  'humor_delta',
  'directness_delta',
  'register_unlocks',
  'trigger_threshold_shifts',
  'sarcasm_bounds',
] as const;
const CLAMP_KEY_OPTIONS = [
  'persona_intensity_max',
  'answer_utility',
  'sarcasm',
  'broadcast_voice',
  'acknowledgement_density',
  'poetic_texture',
  'jokes',
  'warmth',
  'performative_style',
] as const;
const LAYER_MODIFIER_VALUE_PLACEHOLDERS: Record<(typeof LAYER_MODIFIER_KEY_OPTIONS)[number], string> = {
  memory_behavior: 'May reference prior conversations lightly.',
  protective_bias: 'stronger',
  voice_unlocks: 'occasional sincere long sentence',
  humor_delta: '-0.2 or +0.3',
  directness_delta: '-0.1 or +0.2',
  register_unlocks: 'emotional_brief, intimate_chat',
  trigger_threshold_shifts: 'intimacy:-0.15, hostility:+0.10',
  sarcasm_bounds: 'Less likely to mock the user directly.',
};

const toLines = (items: string[] = []): string => items.join('\n');

const toBlocks = (items: string[] = []): string => items.join('\n\n');

const parseLines = (value: string): string[] =>
  value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);

const parseBlocks = (value: string): string[] =>
  value
    .split(/\n\s*\n/g)
    .map((item) => item.trim())
    .filter(Boolean);

const parseNumeric = (value: unknown): number | undefined => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
};

const mappingToLines = (value: Record<string, unknown> = {}): string =>
  Object.entries(value)
    .map(([key, item]) => `${key}: ${String(item)}`)
    .join('\n');

const mappingToEntries = (value: Record<string, unknown> = {}): MappingEntry[] =>
  Object.entries(value).map(([key, item]) => ({ key, value: String(item) }));

const entriesToMapping = (entries: MappingEntry[]): Record<string, string> => {
  const result: Record<string, string> = {};
  for (const entry of entries) {
    const key = entry.key.trim();
    const value = entry.value.trim();
    if (key && value) result[key] = value;
  }
  return result;
};

const linesToMapping = (value: string): Record<string, string> => {
  const result: Record<string, string> = {};
  for (const line of parseLines(value)) {
    const separator = line.indexOf(':');
    if (separator <= 0) continue;
    const key = line.slice(0, separator).trim();
    const item = line.slice(separator + 1).trim();
    if (key) result[key] = item;
  }
  return result;
};

const linesToNumericMapping = (value: string): Record<string, number> => {
  const result: Record<string, number> = {};
  for (const [key, item] of Object.entries(linesToMapping(value))) {
    const parsed = parseNumeric(item);
    if (parsed !== undefined) result[key] = parsed;
  }
  return result;
};

const normalizeModifierLines = (value: unknown): string[] | undefined => {
  if (Array.isArray(value)) {
    const items = value.map((item) => String(item).trim()).filter(Boolean);
    return items.length > 0 ? items : undefined;
  }
  if (typeof value === 'string') {
    const items = parseLines(value);
    return items.length > 0 ? items : undefined;
  }
  return undefined;
};

const normalizeModifierText = (value: unknown): string | undefined => {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed || undefined;
};

const normalizeThresholdShifts = (value: unknown): Record<string, number> | undefined => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const result: Record<string, number> = {};
  for (const [rawKey, rawValue] of Object.entries(value as Record<string, unknown>)) {
    const key = rawKey.trim();
    const parsed = parseNumeric(rawValue);
    if (key && parsed !== undefined) result[key] = parsed;
  }
  return Object.keys(result).length > 0 ? result : undefined;
};

const layerModifiersToEntries = (modifiers: LayerModifiers = {}): LayerModifierEntry[] => {
  const entries: LayerModifierEntry[] = [];
  for (const key of LAYER_MODIFIER_KEY_OPTIONS) {
    const value = modifiers[key];
    if (Array.isArray(value) && value.length === 0) continue;
    if (typeof value === 'object' && value && !Array.isArray(value) && Object.keys(value).length === 0) continue;
    if (value === undefined) continue;
    entries.push({ key, value });
  }
  return entries;
};

const normalizeLayerModifierEntryValue = (
  key: StructuredLayerModifierKey,
  value: LayerModifierValue,
): LayerModifiers[StructuredLayerModifierKey] | undefined => {
  switch (key) {
    case 'voice_unlocks':
    case 'register_unlocks':
      return normalizeModifierLines(value);
    case 'humor_delta':
    case 'directness_delta':
      return parseNumeric(value);
    case 'trigger_threshold_shifts':
      return normalizeThresholdShifts(value);
    case 'memory_behavior':
    case 'protective_bias':
    case 'sarcasm_bounds':
      return normalizeModifierText(value);
    default:
      return undefined;
  }
};

const assignLayerModifierValue = (
  modifiers: LayerModifiers,
  key: StructuredLayerModifierKey,
  value: LayerModifiers[StructuredLayerModifierKey],
): void => {
  switch (key) {
    case 'voice_unlocks':
    case 'register_unlocks':
      if (Array.isArray(value)) modifiers[key] = value;
      break;
    case 'humor_delta':
    case 'directness_delta':
      if (typeof value === 'number') modifiers[key] = value;
      break;
    case 'trigger_threshold_shifts':
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        modifiers.trigger_threshold_shifts = value;
      }
      break;
    case 'memory_behavior':
    case 'protective_bias':
    case 'sarcasm_bounds':
      if (typeof value === 'string') modifiers[key] = value;
      break;
  }
};

const entriesToLayerModifiers = (
  entries: LayerModifierEntry[],
  behaviorShifts?: string[],
): LayerModifiers => {
  const nextModifiers: LayerModifiers = {};
  const seenKeys = new Set<StructuredLayerModifierKey>();
  for (const entry of entries) {
    if (!entry.key || seenKeys.has(entry.key)) continue;
    const normalized = normalizeLayerModifierEntryValue(entry.key, entry.value);
    if (normalized !== undefined) {
      assignLayerModifierValue(nextModifiers, entry.key, normalized);
      seenKeys.add(entry.key);
    }
  }
  if (behaviorShifts && behaviorShifts.length > 0) {
    nextModifiers.behavior_shifts = behaviorShifts;
  }
  return nextModifiers;
};

const normalizeTrigger = (item: Partial<SignatureTrigger> = {}): SignatureTrigger => ({
  trigger_id: item.trigger_id || '',
  activates_when: item.activates_when || '',
  behavior_shift: item.behavior_shift || '',
  intensity_levels: item.intensity_levels || {},
  exit_behavior: item.exit_behavior || '',
});

const normalizeQuietHour = (item: Partial<QuietHour> = {}): QuietHour => ({
  condition: item.condition || '',
  clamps: item.clamps || {},
});

const normalizeLayer = (item: Partial<PersonaLayerItem> = {}): PersonaLayerItem => ({
  layer_id: item.layer_id || '',
  unlock_condition: item.unlock_condition ?? null,
  modifiers: item.modifiers || {},
});

const normalizeRegister = (item?: Partial<PersonaRegister>): PersonaRegister => ({
  description: item?.description || '',
  behavior: item?.behavior || '',
  examples: item?.examples || [],
});

const getLayerModifierValuePlaceholder = (key: string): string => {
  if (key in LAYER_MODIFIER_VALUE_PLACEHOLDERS) {
    return LAYER_MODIFIER_VALUE_PLACEHOLDERS[key as keyof typeof LAYER_MODIFIER_VALUE_PLACEHOLDERS];
  }
  return 'Value';
};

const getDefaultModifierValue = (key: StructuredLayerModifierKey): LayerModifierValue => {
  switch (key) {
    case 'voice_unlocks':
    case 'register_unlocks':
      return [];
    case 'trigger_threshold_shifts':
      return {};
    case 'humor_delta':
    case 'directness_delta':
      return undefined;
    default:
      return '';
  }
};

const Section: React.FC<{
  title: string;
  description?: string;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}> = ({ title, description, defaultOpen = true, open, onOpenChange, children }) => (
  <Collapsible
    className="rounded-md bg-background/60 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.16)]"
    defaultOpen={defaultOpen}
    open={open}
    onOpenChange={onOpenChange}
  >
    <CollapsibleTrigger className="w-full rounded-md px-3 py-2 text-left text-sm font-semibold text-foreground transition hover:bg-accent/50">
      {title}
    </CollapsibleTrigger>
    <CollapsibleContent className="px-3 pb-3 pt-1">
      {description ? <p className="pb-3 text-xs leading-5 text-muted-foreground">{description}</p> : null}
      {children}
    </CollapsibleContent>
  </Collapsible>
);

const HelpTooltip: React.FC<{ label: string; help: string }> = ({ label, help }) => {
  const tooltipId = React.useId();
  const [open, setOpen] = React.useState(false);
  const [align, setAlign] = React.useState<'left' | 'right'>('left');
  const anchorRef = React.useRef<HTMLSpanElement | null>(null);

  const showTooltip = () => {
    const rect = anchorRef.current?.getBoundingClientRect();
    const availableTooltipWidth = Math.min(288, window.innerWidth - 48);
    setAlign(rect && rect.left + availableTooltipWidth > window.innerWidth - 24 ? 'right' : 'left');
    setOpen(true);
  };

  return (
    <span
      ref={anchorRef}
      className="relative inline-flex shrink-0"
      onMouseEnter={showTooltip}
      onMouseLeave={() => setOpen(false)}
      onFocusCapture={showTooltip}
      onBlurCapture={(event) => {
        const nextFocused = event.relatedTarget;
        if (nextFocused instanceof Node && event.currentTarget.contains(nextFocused)) {
          return;
        }
        setOpen(false);
      }}
    >
      <button
        type="button"
        className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-border/70 text-[10px] text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
        aria-label={`${label}: ${help}`}
        aria-describedby={open ? tooltipId : undefined}
      >
        <CircleHelp className="h-3 w-3" />
      </button>
      {open ? (
        <span
          id={tooltipId}
          role="tooltip"
          className={`pointer-events-none absolute top-full z-30 mt-2 w-[min(18rem,calc(100vw-3rem))] max-w-[calc(100vw-3rem)] whitespace-normal break-words rounded-md bg-background px-3 py-2 text-left text-[11px] leading-5 text-foreground shadow-[0_12px_32px_-20px_hsl(var(--foreground)/0.42),inset_0_0_0_1px_hsl(var(--border)/0.55)] ${align === 'right' ? 'right-0' : 'left-0'}`}
        >
          {help}
        </span>
      ) : null}
    </span>
  );
};

const FieldLabel: React.FC<{ label: string; help?: string }> = ({ label, help }) => (
  <span className="inline-flex max-w-full flex-wrap items-center gap-1.5 text-xs font-medium text-muted-foreground">
    <span className="min-w-0">{label}</span>
    {help ? <HelpTooltip label={label} help={help} /> : null}
  </span>
);

const StackedTextareaField: React.FC<{
  label: string;
  help?: string;
  value: string;
  minHeight?: number;
  placeholder?: string;
  onChange: (event: React.ChangeEvent<HTMLTextAreaElement>) => void;
}> = ({ label, help, value, minHeight = 76, placeholder, onChange }) => (
  <label className="block space-y-2 rounded-md bg-muted/20 px-3 py-3 transition-colors duration-200 focus-within:bg-muted/30">
    <FieldLabel label={label} help={help} />
    <AutoResizeTextarea
      value={value}
      minHeight={minHeight}
      placeholder={placeholder}
      className="w-full bg-background/80 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.22)]"
      onChange={onChange}
    />
  </label>
);

const MappingRowsEditor: React.FC<{
  entries: MappingEntry[];
  onChange: (entries: MappingEntry[]) => void;
  keyLabel: string;
  valueLabel: string;
  addLabel: string;
  removeLabel: string;
  keyOptions?: readonly string[];
  allowCustomKey?: boolean;
  getValuePlaceholder?: (key: string) => string;
}> = ({
  entries,
  onChange,
  keyLabel,
  valueLabel,
  addLabel,
  removeLabel,
  keyOptions,
  allowCustomKey = true,
  getValuePlaceholder,
}) => {
  const nextEntries = entries.length > 0 ? entries : [{ key: '', value: '' }];
  return (
    <div className="space-y-2">
      {nextEntries.map((entry, index) => (
        <div key={index} className="grid gap-2 md:grid-cols-[minmax(0,180px)_minmax(0,1fr)_auto]">
          {keyOptions ? (
            <select
              className="h-10 rounded-md border border-input bg-background px-3 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
              aria-label={keyLabel}
              value={entry.key}
              onChange={(event) => {
                const updated = [...nextEntries];
                updated[index] = { ...entry, key: event.target.value };
                onChange(updated);
              }}
            >
              <option value="">{keyLabel}</option>
              {keyOptions.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          ) : (
            <Input
              aria-label={keyLabel}
              placeholder={keyLabel}
              value={entry.key}
              onChange={(event) => {
                const updated = [...nextEntries];
                updated[index] = { ...entry, key: event.target.value };
                onChange(updated);
              }}
            />
          )}
          <Input
            aria-label={valueLabel}
            placeholder={getValuePlaceholder?.(entry.key) || valueLabel}
            value={entry.value}
            onChange={(event) => {
              const updated = [...nextEntries];
              updated[index] = { ...entry, value: event.target.value };
              onChange(updated);
            }}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!allowCustomKey && nextEntries.length === 1}
            onClick={() => {
              const updated = [...nextEntries];
              updated.splice(index, 1);
              onChange(updated);
            }}
          >
            <Trash2 className="h-4 w-4" />
            {removeLabel}
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={() => onChange([...nextEntries, { key: '', value: '' }])}>
        <Plus className="h-4 w-4" />
        {addLabel}
      </Button>
    </div>
  );
};

const LayerModifiersEditor: React.FC<{
  modifiers: LayerModifiers;
  onChange: (modifiers: LayerModifiers) => void;
  addLabel: string;
  removeLabel: string;
  keyLabel: string;
}> = ({ modifiers, onChange, addLabel, removeLabel, keyLabel }) => {
  const behaviorShifts = normalizeModifierLines(modifiers.behavior_shifts);
  const entries = layerModifiersToEntries(modifiers);
  const nextEntries = entries.length > 0 ? entries : [];
  const usedKeys = new Set(nextEntries.map((entry) => entry.key).filter(Boolean));
  const nextAvailableKey = LAYER_MODIFIER_KEY_OPTIONS.find((key) => !usedKeys.has(key));

  const updateEntries = (updated: LayerModifierEntry[]) => {
    onChange(entriesToLayerModifiers(updated, behaviorShifts));
  };

  return (
    <div className="space-y-3">
      {nextEntries.map((entry, index) => {
        const availableOptions = LAYER_MODIFIER_KEY_OPTIONS.filter((option) => option === entry.key || !usedKeys.has(option));
        return (
          <div key={`${entry.key || 'empty'}-${index}`} className="rounded-md border border-border/60 p-3">
            <div className="grid gap-3 md:grid-cols-[minmax(0,220px)_minmax(0,1fr)_auto] md:items-start">
              <select
                className="h-10 rounded-md border border-input bg-background px-3 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
                aria-label={keyLabel}
                value={entry.key}
                onChange={(event) => {
                  const nextKey = event.target.value as StructuredLayerModifierKey;
                  const updated = [...nextEntries];
                  updated[index] = { key: nextKey, value: getDefaultModifierValue(nextKey) };
                  updateEntries(updated);
                }}
              >
                <option value="">{keyLabel}</option>
                {availableOptions.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
              <LayerModifierValueEditor
                modifierKey={entry.key}
                value={entry.value}
                onChange={(nextValue) => {
                  const updated = [...nextEntries];
                  updated[index] = { ...entry, value: nextValue };
                  updateEntries(updated);
                }}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  const updated = [...nextEntries];
                  updated.splice(index, 1);
                  updateEntries(updated);
                }}
              >
                <Trash2 className="h-4 w-4" />
                {removeLabel}
              </Button>
            </div>
          </div>
        );
      })}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!nextAvailableKey}
        onClick={() => {
          if (!nextAvailableKey) return;
          updateEntries([...nextEntries, { key: nextAvailableKey, value: getDefaultModifierValue(nextAvailableKey) }]);
        }}
      >
        <Plus className="h-4 w-4" />
        {addLabel}
      </Button>
    </div>
  );
};

const LayerModifierValueEditor: React.FC<{
  modifierKey: StructuredLayerModifierKey | '';
  value: LayerModifierValue;
  onChange: (value: LayerModifierValue) => void;
}> = ({ modifierKey, value, onChange }) => {
  if (!modifierKey) {
    return <Input aria-label="Modifier Value" placeholder="Select a modifier key first" value="" disabled />;
  }

  switch (modifierKey) {
    case 'voice_unlocks':
    case 'register_unlocks':
      return (
        <AutoResizeTextarea
          aria-label={modifierKey}
          className="w-full"
          placeholder={getLayerModifierValuePlaceholder(modifierKey)}
          value={toLines(normalizeModifierLines(value) || [])}
          onChange={(event) => onChange(parseLines(event.target.value))}
        />
      );
    case 'trigger_threshold_shifts':
      return (
        <AutoResizeTextarea
          aria-label={modifierKey}
          className="w-full"
          placeholder={getLayerModifierValuePlaceholder(modifierKey)}
          value={mappingToLines((normalizeThresholdShifts(value) || {}) as Record<string, unknown>)}
          onChange={(event) => onChange(linesToNumericMapping(event.target.value))}
        />
      );
    case 'humor_delta':
    case 'directness_delta':
      return (
        <Input
          aria-label={modifierKey}
          type="number"
          step="0.05"
          placeholder={getLayerModifierValuePlaceholder(modifierKey)}
          value={parseNumeric(value)?.toString() ?? ''}
          onChange={(event) => onChange(event.target.value)}
        />
      );
    case 'memory_behavior':
    case 'protective_bias':
    case 'sarcasm_bounds':
      return (
        <AutoResizeTextarea
          aria-label={modifierKey}
          className="w-full"
          placeholder={getLayerModifierValuePlaceholder(modifierKey)}
          value={typeof value === 'string' ? value : ''}
          onChange={(event) => onChange(event.target.value)}
        />
      );
    default:
      return <Input aria-label={modifierKey} placeholder={getLayerModifierValuePlaceholder(modifierKey)} value="" disabled />;
  }
};

const PersonalityDetailEditor: React.FC<PersonalityDetailEditorProps> = ({
  config,
  patch,
  t,
  onAvatarUpload,
  uploadingAvatar = false,
  avatarFilename,
}) => {
  const [layersOpen, setLayersOpen] = React.useState(false);
  const [layersUnlocked, setLayersUnlocked] = React.useState(false);
  const [layerConfirmOpen, setLayerConfirmOpen] = React.useState(false);
  const editableLayers = React.useMemo(
    () => (config.persona_layers || [])
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => item.layer_id !== SURFACE_LAYER_ID),
    [config.persona_layers]
  );

  const updateRegister = (key: (typeof REGISTER_KEYS)[number], next: PersonaRegister) => {
    patch((draft) => {
      draft.registers[key] = next;
    });
  };

  const renderBasicProfile = (defaultOpen = true) => (
    <Section
      title={t('personality.sections.basicProfile')}
      description={t('personality.sectionDescriptions.basicProfile')}
      defaultOpen={defaultOpen}
    >
      <div className="grid gap-3 md:grid-cols-2">
        <label className="space-y-1.5">
          <FieldLabel label={t('personality.fields.name')} help={t('personality.fieldHelp.name')} />
          <Input value={config.name} onChange={(event) => patch((draft) => { draft.name = event.target.value; })} />
        </label>
        <label className="space-y-1.5">
          <FieldLabel label={t('personality.fields.description')} help={t('personality.fieldHelp.description')} />
          <Input value={config.description} onChange={(event) => patch((draft) => { draft.description = event.target.value; })} />
        </label>
        {onAvatarUpload && (
          <label className="space-y-1.5 md:col-span-2">
            <FieldLabel label={t('personality.fields.avatar')} help={t('personality.fieldHelp.avatar')} />
            <div className="flex flex-wrap items-center gap-2">
              <input
                id="personality-detail-avatar-upload"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={onAvatarUpload}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={uploadingAvatar}
                onClick={() => document.getElementById('personality-detail-avatar-upload')?.click()}
              >
                <Upload className="h-4 w-4" />
                {uploadingAvatar ? t('personality.actions.uploadingAvatar') : t('personality.actions.uploadAvatar')}
              </Button>
              <span className="text-xs text-muted-foreground">{avatarFilename || t('personality.noAvatar')}</span>
            </div>
          </label>
        )}
      </div>
    </Section>
  );

  const renderIdentityCore = (defaultOpen = true) => (
    <Section title={t('personality.sections.identityCore')} description={t('personality.sectionDescriptions.identityCore')} defaultOpen={defaultOpen}>
      <div className="grid gap-3">
        <label className="space-y-1.5">
          <FieldLabel label={t('personality.fields.identityStatement')} help={t('personality.fieldHelp.identityStatement')} />
          <AutoResizeTextarea
            value={config.identity_core.identity_statement}
            minHeight={120}
            className="w-full"
            onChange={(event) => patch((draft) => { draft.identity_core.identity_statement = event.target.value; })}
          />
        </label>
        <div className="grid gap-3">
          <StackedTextareaField
            label={t('personality.fields.valuesLoved')}
            placeholder={t('personality.placeholders.onePerLine')}
            help={t('personality.fieldHelp.valuesLoved')}
            value={toLines(config.identity_core.values_loved)}
            onChange={(event) => patch((draft) => { draft.identity_core.values_loved = parseLines(event.target.value); })}
          />
          <StackedTextareaField
            label={t('personality.fields.valuesRejected')}
            placeholder={t('personality.placeholders.onePerLine')}
            help={t('personality.fieldHelp.valuesRejected')}
            value={toLines(config.identity_core.values_rejected)}
            onChange={(event) => patch((draft) => { draft.identity_core.values_rejected = parseLines(event.target.value); })}
          />
          <StackedTextareaField
            label={t('personality.fields.attentionBiases')}
            placeholder={t('personality.placeholders.onePerLine')}
            help={t('personality.fieldHelp.attentionBiases')}
            value={toLines(config.identity_core.attention_biases)}
            onChange={(event) => patch((draft) => { draft.identity_core.attention_biases = parseLines(event.target.value); })}
          />
        </div>
      </div>
    </Section>
  );

  const renderIdiolect = (defaultOpen = true) => (
    <Section title={t('personality.sections.idiolect')} description={t('personality.sectionDescriptions.idiolect')} defaultOpen={defaultOpen}>
      <div className="grid gap-3">
        <label className="space-y-1.5">
          <FieldLabel label={t('personality.fields.sentenceStyle')} help={t('personality.fieldHelp.sentenceStyle')} />
          <AutoResizeTextarea
            value={config.idiolect.sentence_style}
            className="w-full"
            onChange={(event) => patch((draft) => { draft.idiolect.sentence_style = event.target.value; })}
          />
        </label>
        <div className="grid gap-3">
          <StackedTextareaField
            label={t('personality.fields.vocabAvailable')}
            placeholder={t('personality.placeholders.onePerLine')}
            help={t('personality.fieldHelp.vocabAvailable')}
            value={toLines(config.idiolect.vocab_available)}
            onChange={(event) => patch((draft) => { draft.idiolect.vocab_available = parseLines(event.target.value); })}
          />
          <StackedTextareaField
            label={t('personality.fields.vocabAvoided')}
            placeholder={t('personality.placeholders.onePerLine')}
            help={t('personality.fieldHelp.vocabAvoided')}
            value={toLines(config.idiolect.vocab_avoided)}
            onChange={(event) => patch((draft) => { draft.idiolect.vocab_avoided = parseLines(event.target.value); })}
          />
          <StackedTextareaField
            label={t('personality.fields.structuralQuirks')}
            placeholder={t('personality.placeholders.onePerLine')}
            help={t('personality.fieldHelp.structuralQuirks')}
            value={toLines(config.idiolect.structural_quirks)}
            onChange={(event) => patch((draft) => { draft.idiolect.structural_quirks = parseLines(event.target.value); })}
          />
        </div>
      </div>
    </Section>
  );

  const renderRegisterEditor = (key: (typeof REGISTER_KEYS)[number]) => {
    const register = normalizeRegister(config.registers[key]);
    return (
      <div key={key} className="rounded-md border border-border/70 p-2">
        <div className="mb-2 text-sm font-medium text-foreground">{t(`personality.registers.${key}`)}</div>
        <div className="grid gap-2">
          <label className="space-y-1.5">
            <FieldLabel label={t('personality.fields.registerDescription')} help={t('personality.fieldHelp.registerDescription')} />
            <Input
              value={register.description}
              placeholder={t('personality.fields.registerDescription')}
              onChange={(event) => updateRegister(key, { ...register, description: event.target.value })}
            />
          </label>
          <label className="space-y-1.5">
            <FieldLabel label={t('personality.fields.registerBehavior')} help={t('personality.fieldHelp.registerBehavior')} />
            <AutoResizeTextarea
              value={register.behavior}
              minHeight={76}
              placeholder={t('personality.fields.registerBehavior')}
              onChange={(event) => updateRegister(key, { ...register, behavior: event.target.value })}
            />
          </label>
          <label className="space-y-1.5">
            <FieldLabel label={t('personality.fields.registerExamples')} help={t('personality.fieldHelp.registerExamples')} />
            <AutoResizeTextarea
              value={toBlocks(register.examples)}
              minHeight={116}
              placeholder={t('personality.placeholders.registerExamples')}
              onChange={(event) => updateRegister(key, { ...register, examples: parseBlocks(event.target.value) })}
            />
          </label>
        </div>
      </div>
    );
  };

  const renderRegisters = (keys: readonly (typeof REGISTER_KEYS)[number][], defaultOpen = true) => (
    <Section title={t('personality.sections.registers')} description={t('personality.sectionDescriptions.registers')} defaultOpen={defaultOpen}>
      <div className="space-y-3">{keys.map(renderRegisterEditor)}</div>
    </Section>
  );

  const renderTriggers = (expert: boolean, defaultOpen = true) => (
    <Section title={t('personality.sections.signatureTriggers')} description={t('personality.sectionDescriptions.signatureTriggers')} defaultOpen={defaultOpen}>
      <div className="space-y-3">
        {config.signature_triggers.map((item, index) => (
          <div key={index} className="rounded-md border border-border/70 p-2">
            <div className="mb-2 text-sm font-medium text-foreground">{t('personality.fields.triggerCard', { index: index + 1 })}</div>
            <div className="grid gap-2">
              <label className="space-y-1.5">
                <FieldLabel label={t('personality.fields.triggerId')} help={t('personality.fieldHelp.triggerId')} />
                <Input value={item.trigger_id} placeholder={t('personality.fields.triggerId')} onChange={(event) => patch((draft) => { draft.signature_triggers[index] = normalizeTrigger({ ...item, trigger_id: event.target.value }); })} />
              </label>
              <label className="space-y-1.5">
                <FieldLabel label={t('personality.fields.activatesWhen')} help={t('personality.fieldHelp.activatesWhen')} />
                <Input value={item.activates_when} placeholder={t('personality.fields.activatesWhen')} onChange={(event) => patch((draft) => { draft.signature_triggers[index] = normalizeTrigger({ ...item, activates_when: event.target.value }); })} />
              </label>
              <label className="space-y-1.5">
                <FieldLabel label={t('personality.fields.behaviorShift')} help={t('personality.fieldHelp.behaviorShift')} />
                <AutoResizeTextarea value={item.behavior_shift} minHeight={76} placeholder={t('personality.fields.behaviorShift')} onChange={(event) => patch((draft) => { draft.signature_triggers[index] = normalizeTrigger({ ...item, behavior_shift: event.target.value }); })} />
              </label>
              {expert && (
                <>
                  <label className="space-y-1.5">
                    <FieldLabel label={t('personality.fields.intensityLevels')} help={t('personality.fieldHelp.intensityLevels')} />
                    <AutoResizeTextarea value={mappingToLines(item.intensity_levels)} placeholder={t('personality.fields.intensityLevels')} onChange={(event) => patch((draft) => { draft.signature_triggers[index] = normalizeTrigger({ ...item, intensity_levels: linesToMapping(event.target.value) }); })} />
                  </label>
                  <label className="space-y-1.5">
                    <FieldLabel label={t('personality.fields.exitBehavior')} help={t('personality.fieldHelp.exitBehavior')} />
                    <Input value={item.exit_behavior} placeholder={t('personality.fields.exitBehavior')} onChange={(event) => patch((draft) => { draft.signature_triggers[index] = normalizeTrigger({ ...item, exit_behavior: event.target.value }); })} />
                  </label>
                </>
              )}
              <div className="flex justify-end">
                <Button type="button" variant="outline" size="sm" disabled={config.signature_triggers.length === 1} onClick={() => patch((draft) => { if (draft.signature_triggers.length > 1) draft.signature_triggers.splice(index, 1); })}>
                  <Trash2 className="h-4 w-4" />
                  {t('personality.actions.removeTrigger')}
                </Button>
              </div>
            </div>
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" onClick={() => patch((draft) => { draft.signature_triggers.push(normalizeTrigger()); })}>
          <Plus className="h-4 w-4" />
          {t('personality.actions.addTrigger')}
        </Button>
      </div>
    </Section>
  );

  const renderQuietHours = (defaultOpen = true) => (
    <Section title={t('personality.sections.quietHours')} description={t('personality.sectionDescriptions.quietHours')} defaultOpen={defaultOpen}>
      <div className="space-y-3">
        {config.quiet_hours.map((item, index) => (
          <div key={index} className="rounded-md border border-border/70 p-2">
            <div className="mb-2 text-sm font-medium text-foreground">{t('personality.fields.quietHourCard', { index: index + 1 })}</div>
            <div className="grid gap-2">
              <label className="space-y-1.5">
                <FieldLabel label={t('personality.fields.quietHourCondition')} help={t('personality.fieldHelp.quietHourCondition')} />
                <Input value={item.condition} placeholder={t('personality.fields.quietHourCondition')} onChange={(event) => patch((draft) => { draft.quiet_hours[index] = normalizeQuietHour({ ...item, condition: event.target.value }); })} />
              </label>
              <div className="space-y-1.5">
                <FieldLabel label={t('personality.fields.clamps')} help={t('personality.fieldHelp.clamps')} />
                <MappingRowsEditor
                  entries={mappingToEntries(item.clamps)}
                  onChange={(entries) => patch((draft) => { draft.quiet_hours[index] = normalizeQuietHour({ ...item, clamps: entriesToMapping(entries) }); })}
                  keyLabel={t('personality.fields.clampKey')}
                  valueLabel={t('personality.fields.clampValue')}
                  addLabel={t('personality.actions.addClamp')}
                  removeLabel={t('personality.actions.removeClamp')}
                  keyOptions={CLAMP_KEY_OPTIONS}
                />
              </div>
              <div className="flex justify-end">
                <Button type="button" variant="outline" size="sm" onClick={() => patch((draft) => { draft.quiet_hours.splice(index, 1); })}>
                  <Trash2 className="h-4 w-4" />
                  {t('personality.actions.removeQuietHour')}
                </Button>
              </div>
            </div>
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" onClick={() => patch((draft) => { draft.quiet_hours.push(normalizeQuietHour()); })}>
          <Plus className="h-4 w-4" />
          {t('personality.actions.addQuietHour')}
        </Button>
      </div>
    </Section>
  );

  const renderAppearance = () => (
    <Section title={t('personality.sections.appearance')} description={t('personality.sectionDescriptions.appearance')} defaultOpen={false}>
      <label className="space-y-1.5">
        <FieldLabel label={t('personality.fields.appearancePrompt')} help={t('personality.fieldHelp.appearancePrompt')} />
        <AutoResizeTextarea value={config.appearance_prompt} className="w-full" onChange={(event) => patch((draft) => { draft.appearance_prompt = event.target.value; })} />
      </label>
    </Section>
  );

  const handleLayersOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setLayersOpen(false);
      return;
    }
    if (layersUnlocked) {
      setLayersOpen(true);
      return;
    }
    setLayerConfirmOpen(true);
  };

  const renderLayers = () => (
    <Section
      title={t('personality.sections.personaLayers')}
      description={t('personality.sectionDescriptions.personaLayers')}
      defaultOpen={false}
      open={layersOpen}
      onOpenChange={handleLayersOpenChange}
    >
      <div className="space-y-3">
        {editableLayers.map(({ item, index }) => (
          <div key={index} className="rounded-md border border-border/70 p-2">
            <div className="mb-2 text-sm font-medium text-foreground">{t('personality.fields.layerCard', { index: index + 1 })}</div>
            <div className="grid gap-2">
              <label className="space-y-1.5">
                <FieldLabel label={t('personality.fields.layerId')} help={t('personality.help.layerId')} />
                <Input value={item.layer_id} placeholder={t('personality.fields.layerId')} onChange={(event) => patch((draft) => { draft.persona_layers[index] = normalizeLayer({ ...item, layer_id: event.target.value }); })} />
              </label>
              <div className="rounded-md border border-border/60 p-3">
                <div className="mb-2">
                  <FieldLabel label={t('personality.fields.unlockCondition')} help={t('personality.help.unlockCondition')} />
                </div>
                <div className="grid gap-2 md:grid-cols-3">
                  <label className="space-y-1.5">
                    <FieldLabel label={t('personality.fields.trustLevelGte')} help={t('personality.help.trustLevelGte')} />
                    <Input
                      value={String(item.unlock_condition?.trust_level_gte ?? '')}
                      placeholder={t('personality.fields.trustLevelGtePlaceholder')}
                      onChange={(event) => patch((draft) => {
                        const unlock = { ...(item.unlock_condition || {}) } as Record<string, unknown>;
                        const value = event.target.value.trim();
                        if (value) unlock.trust_level_gte = value;
                        else delete unlock.trust_level_gte;
                        draft.persona_layers[index] = normalizeLayer({ ...item, unlock_condition: Object.keys(unlock).length ? unlock : null });
                      })}
                    />
                  </label>
                  <label className="space-y-1.5">
                    <FieldLabel label={t('personality.fields.interactionCountGte')} help={t('personality.help.interactionCountGte')} />
                    <Input
                      value={String(item.unlock_condition?.interaction_count_gte ?? '')}
                      placeholder={t('personality.fields.interactionCountGtePlaceholder')}
                      onChange={(event) => patch((draft) => {
                        const unlock = { ...(item.unlock_condition || {}) } as Record<string, unknown>;
                        const value = event.target.value.trim();
                        if (value) unlock.interaction_count_gte = value;
                        else delete unlock.interaction_count_gte;
                        draft.persona_layers[index] = normalizeLayer({ ...item, unlock_condition: Object.keys(unlock).length ? unlock : null });
                      })}
                    />
                  </label>
                  <label className="space-y-1.5">
                    <FieldLabel label={t('personality.fields.milestoneRequired')} help={t('personality.help.milestoneRequired')} />
                    <Input
                      value={String(item.unlock_condition?.milestone_required ?? '')}
                      placeholder={t('personality.fields.milestoneRequiredPlaceholder')}
                      onChange={(event) => patch((draft) => {
                        const unlock = { ...(item.unlock_condition || {}) } as Record<string, unknown>;
                        const value = event.target.value.trim();
                        if (value) unlock.milestone_required = value;
                        else delete unlock.milestone_required;
                        draft.persona_layers[index] = normalizeLayer({ ...item, unlock_condition: Object.keys(unlock).length ? unlock : null });
                      })}
                    />
                  </label>
                </div>
              </div>
              <label className="space-y-1.5">
                <FieldLabel label={t('personality.fields.behaviorHints')} help={t('personality.help.behaviorHints')} />
                <AutoResizeTextarea
                  value={toLines(Array.isArray(item.modifiers?.behavior_shifts) ? item.modifiers.behavior_shifts.map((entry) => String(entry)) : [])}
                  placeholder={t('personality.fields.behaviorHints')}
                  onChange={(event) => patch((draft) => {
                    const modifiers = { ...(item.modifiers || {}) } as Record<string, unknown>;
                    const behaviorShifts = parseLines(event.target.value);
                    if (behaviorShifts.length > 0) modifiers.behavior_shifts = behaviorShifts;
                    else delete modifiers.behavior_shifts;
                    draft.persona_layers[index] = normalizeLayer({ ...item, modifiers });
                  })}
                />
              </label>
              <div className="space-y-1.5">
                <FieldLabel label={t('personality.fields.layerModifiers')} help={t('personality.help.layerModifiers')} />
                <LayerModifiersEditor
                  modifiers={item.modifiers || {}}
                  onChange={(modifiers) => patch((draft) => {
                    draft.persona_layers[index] = normalizeLayer({ ...item, modifiers });
                  })}
                  addLabel={t('personality.actions.addModifier')}
                  removeLabel={t('personality.actions.removeModifier')}
                  keyLabel={t('personality.fields.overrideKeyPlaceholder')}
                />
              </div>
              <div className="flex justify-end">
                <Button type="button" variant="outline" size="sm" onClick={() => patch((draft) => { draft.persona_layers.splice(index, 1); })}>
                  <Trash2 className="h-4 w-4" />
                  {t('personality.actions.removeLayer')}
                </Button>
              </div>
            </div>
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" onClick={() => patch((draft) => { draft.persona_layers.push(normalizeLayer({ layer_id: 'crack' })); })}>
          <Plus className="h-4 w-4" />
          {t('personality.actions.addLayer')}
        </Button>
      </div>
    </Section>
  );

  return (
    <div className="space-y-3 pr-1">
      <div className="space-y-1">
        {renderBasicProfile()}
        {renderIdentityCore(false)}
        {renderIdiolect(false)}
        {renderRegisters(REGISTER_KEYS, false)}
        {renderTriggers(true, false)}
        {renderQuietHours(false)}
        {renderAppearance()}
        {renderLayers()}
      </div>

      <Dialog open={layerConfirmOpen} onOpenChange={setLayerConfirmOpen}>
        <DialogContent className="max-w-[420px] overflow-hidden rounded-xl border-border/45 bg-card/95 p-0 shadow-[0_24px_80px_hsl(var(--foreground)/0.14)]">
          <div className="flex items-start gap-3 px-5 pb-3 pt-5">
            <span
              aria-hidden="true"
              className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.12)]"
            >
              <Info className="h-4 w-4" />
            </span>
            <div className="min-w-0 space-y-1.5 pr-8">
              <DialogTitle className="text-[15px] font-semibold leading-6 text-foreground">
                {t('personality.actions.viewLayersTitle')}
              </DialogTitle>
              <DialogDescription className="text-[13px] leading-5 text-muted-foreground">
                {t('personality.actions.viewLayersConfirm')}
              </DialogDescription>
            </div>
          </div>
          <div
            data-testid="personality-layer-confirm-actions"
            className="flex items-center justify-end gap-2 px-5 pb-5 pt-2"
          >
            <Button
              type="button"
              variant="outline"
              className="h-9 rounded-md px-4"
              onClick={() => setLayerConfirmOpen(false)}
            >
              {t('personality.cancel')}
            </Button>
            <Button
              type="button"
              className="h-9 rounded-md px-4 shadow-[0_10px_24px_hsl(var(--primary)/0.16)]"
              onClick={() => {
                setLayersUnlocked(true);
                setLayersOpen(true);
                setLayerConfirmOpen(false);
              }}
            >
              {t('personality.actions.viewLayersReveal')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default PersonalityDetailEditor;
