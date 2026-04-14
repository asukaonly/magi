/**
 * Dynamic Tool Configuration Components
 *
 * Renders tool configuration forms dynamically based on API-provided specs.
 */
import React, { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronDown,
  ChevronUp,
  AlertCircle,
  CheckCircle,
  Eye,
  EyeOff,
  FolderOpen,
  X,
  Plus,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { SelectField } from '@/components/config-forms/fields';
import { type ToolConfig, ToolConfigSpec } from '@/api/modules/tools';
import type { ExtensionFieldSpec } from '@/api/modules/plugins';

export type DynamicConfigSpec = ToolConfigSpec | ExtensionFieldSpec;

type NormalizedDynamicConfigSpec = {
  inputKind: 'boolean' | 'select' | 'secret' | 'number' | 'string' | 'array' | 'json' | 'path_list' | 'checkbox_group';
  label: string;
  description?: string;
  required: boolean;
  placeholder?: string;
  readOnly: boolean;
  sensitive: boolean;
  defaultValue?: any;
  enumValues?: any[];
};

const isExtensionFieldSpec = (spec: DynamicConfigSpec): spec is ExtensionFieldSpec => 'key' in spec;

const normalizeDynamicSpec = (
  spec: DynamicConfigSpec,
  providerName?: string
): NormalizedDynamicConfigSpec => {
  if (isExtensionFieldSpec(spec)) {
    const enumValues = spec.type === 'select'
      ? spec.options.map((option) => option.value)
      : spec.type === 'tags' && spec.options.length > 0
        ? spec.options.map((option) => option.value)
        : undefined;
    const inputKind = (() => {
      switch (spec.type) {
        case 'switch':
          return 'boolean';
        case 'select':
          return 'select';
        case 'secret':
          return 'secret';
        case 'number':
          return 'number';
        case 'tags':
          // tags with predefined options → render as checkboxes
          return spec.options.length > 0 ? 'checkbox_group' : 'array';
        case 'path':
          // path with array default → folder list picker
          return Array.isArray(spec.default) ? 'path_list' : 'string';
        case 'input':
          return 'string';
        default:
          return 'string';
      }
    })();
    return {
      inputKind,
      label: spec.label,
      description: spec.description,
      required: spec.required,
      placeholder: spec.placeholder ?? undefined,
      readOnly: false,
      sensitive: spec.type === 'secret',
      defaultValue: spec.default,
      enumValues,
    };
  }

  const label = spec.is_template && providerName
    ? spec.description.replace('{provider}', providerName)
    : spec.description;
  const inputKind = (() => {
    if (spec.type === 'boolean') {
      return 'boolean';
    }
    if (spec.type === 'string' && spec.enum && spec.enum.length > 0) {
      return 'select';
    }
    if (spec.type === 'string' && spec.sensitive) {
      return 'secret';
    }
    if (spec.type === 'integer' || spec.type === 'float') {
      return 'number';
    }
    if (spec.type === 'array') {
      return 'array';
    }
    if (spec.type === 'object') {
      return 'json';
    }
    return 'string';
  })();

  return {
    inputKind,
    label,
    required: spec.required,
    placeholder: spec.placeholder,
    readOnly: spec.read_only,
    sensitive: spec.sensitive,
    defaultValue: spec.default,
    enumValues: spec.enum,
  };
};

interface DynamicConfigFieldProps {
  spec: DynamicConfigSpec;
  value: any;
  onChange: (value: any) => void;
  disabled?: boolean;
  providerName?: string;
  selectOptions?: Array<{ label: string; value: string; disabled?: boolean }>;
}

export const DynamicConfigField: React.FC<DynamicConfigFieldProps> = ({
  spec,
  value,
  onChange,
  disabled = false,
  providerName,
  selectOptions,
}) => {
  const { t } = useTranslation('app');
  const [showPassword, setShowPassword] = useState(false);
  const [tagInput, setTagInput] = useState('');
  const normalized = normalizeDynamicSpec(spec, providerName);

  const handleChange = useCallback(
    (newValue: any) => {
      if (!disabled) {
        onChange(newValue);
      }
    },
    [disabled, onChange]
  );

  const renderLabel = () => (
    <span className="text-sm font-medium">
      {normalized.label}
      {normalized.required ? <span className="ml-1 text-destructive">*</span> : null}
    </span>
  );

  const renderField = () => {
    if (normalized.inputKind === 'boolean') {
      return (
        <label className="flex items-center justify-between">
          {renderLabel()}
          <Switch
            checked={!!value}
            onCheckedChange={handleChange}
            disabled={disabled || normalized.readOnly}
          />
        </label>
      );
    }

    if (normalized.inputKind === 'select') {
      const options = selectOptions ?? (normalized.enumValues || []).map((item) => ({
        label: String(item),
        value: String(item),
      }));

      return (
        <label className="space-y-2">
          {renderLabel()}
          <SelectField
            value={String(value ?? normalized.defaultValue ?? '')}
            onChange={handleChange}
            options={options}
            placeholder={normalized.placeholder || t('settings.selectPlaceholder')}
            disabled={disabled || normalized.readOnly}
            allowEmpty={!normalized.required}
          />
        </label>
      );
    }

    if (normalized.inputKind === 'secret') {
      const sensitivePlaceholder = value ? '•••••••••' : undefined;
      return (
        <label className="space-y-2">
          {renderLabel()}
          <div className="relative">
            <Input
              type={showPassword ? 'text' : 'password'}
              value={value ?? ''}
              onChange={(e) => handleChange(e.target.value)}
              placeholder={normalized.placeholder || sensitivePlaceholder}
              disabled={disabled || normalized.readOnly}
              className="pr-10"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label={showPassword ? t('settings.hideSensitiveValue') : t('settings.showSensitiveValue')}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </label>
      );
    }

    if (normalized.inputKind === 'number') {
      return (
        <label className="space-y-2">
          {renderLabel()}
          <input
            type="number"
            value={value ?? normalized.defaultValue ?? ''}
            onChange={(e) => handleChange(e.target.value === '' ? '' : Number(e.target.value))}
            placeholder={normalized.placeholder}
            disabled={disabled || normalized.readOnly}
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
          />
        </label>
      );
    }

    if (normalized.inputKind === 'string') {
      return (
        <label className="space-y-2">
          {renderLabel()}
          <Input
            value={value ?? ''}
            onChange={(e) => handleChange(e.target.value)}
            placeholder={normalized.placeholder}
            disabled={disabled || normalized.readOnly}
          />
        </label>
      );
    }

    if (normalized.inputKind === 'path_list') {
      const paths: string[] = Array.isArray(value) ? value : [];
      const handleBrowse = async () => {
        try {
          const { pickDirectory } = await import('@/runtime/desktop');
          const selected = await pickDirectory(paths[paths.length - 1] ?? undefined);
          if (selected && !paths.includes(selected)) {
            handleChange([...paths, selected]);
          }
        } catch {
          // Not in Tauri runtime — ignore
        }
      };
      const handleRemove = (index: number) => {
        handleChange(paths.filter((_, i) => i !== index));
      };
      return (
        <div className="space-y-2">
          {renderLabel()}
          {paths.length > 0 && (
            <div className="space-y-1.5">
              {paths.map((p, i) => (
                <div key={i} className="flex items-center gap-2 rounded-md border border-input bg-background px-3 py-1.5 text-sm">
                  <FolderOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="flex-1 truncate" title={p}>{p}</span>
                  {!disabled && !normalized.readOnly && (
                    <button
                      type="button"
                      onClick={() => handleRemove(i)}
                      className="shrink-0 text-muted-foreground hover:text-destructive"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
          {!disabled && !normalized.readOnly && (
            <button
              type="button"
              onClick={handleBrowse}
              className="flex items-center gap-1.5 rounded-md border border-dashed border-input px-3 py-1.5 text-sm text-muted-foreground hover:border-primary hover:text-foreground transition-colors"
            >
              <Plus className="h-3.5 w-3.5" />
              {normalized.placeholder || t('settings.browseFolder')}
            </button>
          )}
        </div>
      );
    }

    if (normalized.inputKind === 'checkbox_group') {
      const selected: string[] = Array.isArray(value) ? value : [];
      const options = selectOptions ?? (normalized.enumValues || []).map((v) => ({
        label: String(v),
        value: String(v),
      }));
      const handleToggle = (optionValue: string) => {
        if (selected.includes(optionValue)) {
          handleChange(selected.filter((v) => v !== optionValue));
        } else {
          handleChange([...selected, optionValue]);
        }
      };
      return (
        <div className="space-y-2">
          {renderLabel()}
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {options.map((opt) => (
              <label key={opt.value} className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={selected.includes(opt.value)}
                  onChange={() => handleToggle(opt.value)}
                  disabled={disabled || normalized.readOnly}
                  className="h-4 w-4 rounded border-input accent-primary"
                />
                {opt.label}
              </label>
            ))}
          </div>
        </div>
      );
    }

    if (normalized.inputKind === 'array') {
      const tags: string[] = Array.isArray(value) ? value : [];
      const handleAdd = () => {
        const trimmed = tagInput.trim();
        if (trimmed && !tags.includes(trimmed)) {
          handleChange([...tags, trimmed]);
        }
        setTagInput('');
      };
      const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          handleAdd();
        }
      };
      const handleRemoveTag = (index: number) => {
        handleChange(tags.filter((_, i) => i !== index));
      };
      return (
        <div className="space-y-2">
          {renderLabel()}
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {tags.map((tag, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground"
                >
                  {tag}
                  {!disabled && !normalized.readOnly && (
                    <button
                      type="button"
                      onClick={() => handleRemoveTag(i)}
                      className="text-muted-foreground hover:text-destructive"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </span>
              ))}
            </div>
          )}
          {!disabled && !normalized.readOnly && (
            <div className="flex gap-2">
              <Input
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={normalized.placeholder || t('settings.arrayPlaceholder')}
                className="flex-1"
              />
              <button
                type="button"
                onClick={handleAdd}
                disabled={!tagInput.trim()}
                className="flex items-center gap-1 rounded-md border border-input px-2.5 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-40 transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      );
    }

    return (
      <label className="space-y-2">
        {renderLabel()}
        <textarea
          value={typeof value === 'object' ? JSON.stringify(value, null, 2) : ''}
          onChange={(e) => {
            try {
              const parsed = JSON.parse(e.target.value);
              handleChange(parsed);
            } catch {
              // Keep invalid JSON local until it becomes valid.
            }
          }}
          placeholder={normalized.placeholder || '{}'}
          disabled={disabled || normalized.readOnly}
          rows={3}
          className="h-20 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
        />
      </label>
    );
  };

  return <div className="space-y-1">{renderField()}</div>;
};

interface ToolConfigCardProps {
  tool: ToolConfig;
  values: Record<string, any>;
  enabled: boolean;
  onUpdateConfig: (toolName: string, path: string, value: any) => void;
  onUpdateEnabled: (toolName: string, enabled: boolean) => void;
  disabled?: boolean;
}

export const ToolConfigCard: React.FC<ToolConfigCardProps> = ({
  tool,
  values,
  enabled,
  onUpdateConfig,
  onUpdateEnabled,
  disabled = false,
}) => {
  const { t } = useTranslation('app');
  const [expandedProviders, setExpandedProviders] = useState<Set<string>>(new Set());

  const toggleProvider = (providerName: string) => {
    setExpandedProviders((prev) => {
      const next = new Set(prev);
      if (next.has(providerName)) {
        next.delete(providerName);
      } else {
        next.add(providerName);
      }
      return next;
    });
  };

  const templateSpecs = tool.config_specs.filter((spec) => spec.is_template);
  const regularSpecs = tool.config_specs.filter((spec) => !spec.is_template);
  const providerReadyMap = new Map(tool.providers.map((provider) => [provider.name, provider.is_ready]));

  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <CardTitle className="text-base">{tool.display_name}</CardTitle>
              {tool.is_ready ? (
                <Badge variant="default" className="text-xs">
                  <CheckCircle className="mr-1 h-3 w-3" />
                  {t('settings.toolStatus.ready')}
                </Badge>
              ) : (
                <Badge variant="secondary" className="text-xs">
                  <AlertCircle className="mr-1 h-3 w-3" />
                  {t('settings.toolStatus.notConfigured')}
                </Badge>
              )}
            </div>
            <CardDescription className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
              {tool.description}
            </CardDescription>
          </div>
          <Switch
            checked={enabled}
            onCheckedChange={(checked) => onUpdateEnabled(tool.name, checked)}
            disabled={disabled}
          />
        </div>
      </CardHeader>

      <CardContent className="pt-0">
        {regularSpecs.length > 0 ? (
          <div className="mb-4 space-y-3">
            {regularSpecs.map((spec) => (
              <DynamicConfigField
                key={spec.path}
                spec={spec}
                value={values[spec.path] ?? tool.current_values[spec.path]}
                onChange={(value) => onUpdateConfig(tool.name, spec.path, value)}
                disabled={disabled}
                selectOptions={
                  spec.path === 'default_provider' && spec.enum
                    ? spec.enum.map((item) => {
                        const providerName = String(item);
                        const isKnownProvider = providerReadyMap.has(providerName);
                        const isReady = providerReadyMap.get(providerName);
                        return {
                          label: providerName,
                          value: providerName,
                          disabled: isKnownProvider ? !isReady : false,
                        };
                      })
                    : undefined
                }
              />
            ))}
          </div>
        ) : null}

        {tool.is_multi_provider && templateSpecs.length > 0 ? (
          <div className="mt-4 border-t pt-4">
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-sm font-medium">{t('settings.toolProviders')}</h4>
            </div>
            <div className="space-y-2">
              {tool.providers.map((provider) => (
                <div key={provider.name} className="overflow-hidden rounded-lg border">
                  <button
                    type="button"
                    onClick={() => toggleProvider(provider.name)}
                    className="flex w-full items-center justify-between bg-muted/30 p-3 transition-colors hover:bg-muted/50"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{provider.display_name}</span>
                      {provider.is_ready ? (
                        <Badge variant="default" className="text-xs">
                          {t('settings.providerStatus.ready')}
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-xs">
                          {t('settings.providerStatus.notConfigured')}
                        </Badge>
                      )}
                    </div>
                    {expandedProviders.has(provider.name) ? (
                      <ChevronUp className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    )}
                  </button>
                  {expandedProviders.has(provider.name) ? (
                    <div className="space-y-3 border-t bg-background p-3">
                      {templateSpecs
                        .filter((spec) => !spec.providers || spec.providers.includes(provider.name))
                        .map((spec) => (
                          <DynamicConfigField
                            key={`${spec.path}-${provider.name}`}
                            spec={spec}
                            value={
                              values[spec.path.replace('{provider}', provider.name)] ??
                              tool.current_values[spec.path.replace('{provider}', provider.name)]
                            }
                            onChange={(value) =>
                              onUpdateConfig(tool.name, spec.path.replace('{provider}', provider.name), value)
                            }
                            disabled={disabled}
                            providerName={provider.name}
                          />
                        ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
};

interface DynamicToolsConfigProps {
  tools: ToolConfig[];
  loading?: boolean;
  error?: string | null;
  drafts: Record<string, { enabled: boolean; values: Record<string, any> }>;
  onUpdateConfig: (toolName: string, path: string, value: any) => void;
  onUpdateEnabled: (toolName: string, enabled: boolean) => void;
}

export const DynamicToolsConfig: React.FC<DynamicToolsConfigProps> = ({
  tools,
  loading = false,
  error = null,
  drafts,
  onUpdateConfig,
  onUpdateEnabled,
}) => {
  const { t } = useTranslation('app');

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="flex items-center gap-2 text-muted-foreground">
          <LoadingSpinner />
          <span className="text-sm">{t('settings.loadingTools')}</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {tools.map((tool) => (
        <ToolConfigCard
          key={tool.name}
          tool={tool}
          values={drafts[tool.name]?.values || {}}
          enabled={drafts[tool.name]?.enabled ?? tool.enabled}
          onUpdateConfig={onUpdateConfig}
          onUpdateEnabled={onUpdateEnabled}
        />
      ))}
    </div>
  );
};

export default DynamicToolsConfig;
