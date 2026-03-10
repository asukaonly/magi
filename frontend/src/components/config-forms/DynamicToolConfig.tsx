/**
 * Dynamic Tool Configuration Components
 *
 * Renders tool configuration forms dynamically based on API-provided specs.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import {
  ChevronDown,
  ChevronUp,
  AlertCircle,
  CheckCircle,
  Eye,
  EyeOff,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { SelectField } from '@/components/config-forms/fields';
import { toolsApi, type ToolConfig, ToolConfigSpec } from '@/api/modules/tools';

/**
 * DynamicConfigField - Renders a single config field based on spec
 */
interface DynamicConfigFieldProps {
  spec: ToolConfigSpec;
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

  const handleChange = useCallback(
    (newValue: any) => {
    if (!disabled) {
      onChange(newValue);
    }
  },
    [disabled, onChange]
  );

  // Get display label
  const getLabel = () => {
    if (spec.is_template && providerName) {
      return spec.description.replace('{provider}', providerName);
    }
    return spec.description;
  };

  const renderLabel = () => (
    <span className="text-sm font-medium">
      {getLabel()}
      {spec.required ? <span className="ml-1 text-destructive">*</span> : null}
    </span>
  );

  // Render based on type
  const renderField = () => {
    // Boolean -> Switch
    if (spec.type === 'boolean') {
      return (
        <label className="flex items-center justify-between">
          {renderLabel()}
          <Switch
            checked={!!value}
            onCheckedChange={handleChange}
            disabled={disabled || spec.read_only}
          />
        </label>
      );
    }

    // String with enum -> Select
    if (spec.type === 'string' && spec.enum && spec.enum.length > 0) {
      const options = selectOptions ?? spec.enum.map((item) => ({
        label: String(item),
        value: String(item),
      }));

      return (
        <label className="space-y-2">
          {renderLabel()}
          <SelectField
            value={String(value ?? spec.default ?? '')}
            onChange={handleChange}
            options={options}
            placeholder={spec.placeholder || t('settings.selectPlaceholder')}
            disabled={disabled || spec.read_only}
            allowEmpty={!spec.required}
          />
        </label>
      );
    }

    // Sensitive string (API key, etc.) -> Password Input
    if (spec.type === 'string' && spec.sensitive) {
      const sensitivePlaceholder = value ? '•••••••••' : undefined;
      return (
        <label className="space-y-2">
          {renderLabel()}
          <div className="relative">
            <Input
              type={showPassword ? 'text' : 'password'}
              value={value ?? ''}
              onChange={(e) => handleChange(e.target.value)}
              placeholder={spec.placeholder || sensitivePlaceholder}
              disabled={disabled || spec.read_only}
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

    // Integer/Float -> Number Input
    if (spec.type === 'integer' || spec.type === 'float') {
      return (
        <label className="space-y-2">
          {renderLabel()}
          <input
            type="number"
            value={value ?? spec.default ?? ''}
            onChange={(e) => handleChange(spec.type === 'integer' ? parseInt(e.target.value) : parseFloat(e.target.value))}
            placeholder={spec.placeholder}
            disabled={disabled || spec.read_only}
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
          />
        </label>
      );
    }

    // Default string -> Text Input
    if (spec.type === 'string') {
      return (
        <label className="space-y-2">
          {renderLabel()}
          <Input
            value={value ?? ''}
            onChange={(e) => handleChange(e.target.value)}
            placeholder={spec.placeholder}
            disabled={disabled || spec.read_only}
          />
        </label>
      );
    }

    // Array -> Textarea (comma-separated)
    if (spec.type === 'array') {
      const arrayValue = Array.isArray(value) ? value.join(', ') : '';
      return (
        <label className="space-y-2">
          {renderLabel()}
          <textarea
            value={arrayValue}
            onChange={(e) => {
              const arr = e.target.value.split(',').map((s: string) => s.trim()).filter(Boolean);
              handleChange(arr);
            }}
            placeholder={spec.placeholder || t('settings.arrayPlaceholder')}
            disabled={disabled || spec.read_only}
            rows={2}
            className="h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
          />
        </label>
      );
    }

    // Object or unknown type -> JSON Textarea
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
              // Invalid JSON, don't update
            }
          }}
          placeholder={spec.placeholder || '{}'}
          disabled={disabled || spec.read_only}
          rows={3}
          className="h-20 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
        />
      </label>
    );
  };

  return <div className="space-y-1">{renderField()}</div>;
};

/**
 * ToolConfigCard - Renders a single tool's configuration card
 */
interface ToolConfigCardProps {
  tool: ToolConfig;
  onUpdateConfig: (toolName: string, updates: Record<string, any>) => Promise<boolean>;
  onUpdateEnabled: (toolName: string, enabled: boolean) => void;
  saving?: boolean;
}

 export const ToolConfigCard: React.FC<ToolConfigCardProps> = ({
  tool,
  onUpdateConfig,
  onUpdateEnabled,
  saving = false,
}) => {
  const { t } = useTranslation('app');
  const [expandedProviders, setExpandedProviders] = useState<Set<string>>(new Set());
  const [pendingChanges, setPendingChanges] = useState<Record<string, any>>({});

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
  }

  const handleFieldChange = (path: string, value: any) => {
    setPendingChanges((prev) => ({ ...prev, [path]: value }));
  };

  useEffect(() => {
    if (saving || Object.keys(pendingChanges).length === 0) {
      return;
    }

    const timer = window.setTimeout(async () => {
      const saved = await onUpdateConfig(tool.name, pendingChanges);
      if (saved) {
        setPendingChanges({});
      }
    }, 600);

    return () => {
      window.clearTimeout(timer);
    };
  }, [onUpdateConfig, pendingChanges, saving, tool.name]);

  // Separate template specs from regular specs
  const templateSpecs = tool.config_specs.filter((s) => s.is_template);
  const regularSpecs = tool.config_specs.filter((s) => !s.is_template);
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
            checked={tool.enabled}
            onCheckedChange={(checked) => onUpdateEnabled(tool.name, checked)}
            disabled={saving}
          />
        </div>
      </CardHeader>

      <CardContent className="pt-0">
        {/* Regular config fields */}
        {regularSpecs.length > 0 && (
          <div className="space-y-3 mb-4">
            {regularSpecs.map((spec) => (
              <DynamicConfigField
                key={spec.path}
                spec={spec}
                value={pendingChanges[spec.path] ?? tool.current_values[spec.path]}
                onChange={(value) => handleFieldChange(spec.path, value)}
                disabled={saving}
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
        )}

        {/* Multi-provider config */}
        {tool.is_multi_provider && templateSpecs.length > 0 && (
          <div className="mt-4 border-t pt-4">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-medium">{t('settings.toolProviders')}</h4>
            </div>
            <div className="space-y-2">
              {tool.providers.map((provider) => (
                <div key={provider.name} className="border rounded-lg overflow-hidden">
                  <button
                    type="button"
                    onClick={() => toggleProvider(provider.name)}
                    className="flex w-full items-center justify-between p-3 bg-muted/30 hover:bg-muted/50 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm">{provider.display_name}</span>
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
                  {expandedProviders.has(provider.name) && (
                    <div className="p-3 border-t space-y-3 bg-background">
                      {templateSpecs
                        .filter((spec) => !spec.providers || spec.providers.includes(provider.name))
                        .map((spec) => (
                        <DynamicConfigField
                          key={`${spec.path}-${provider.name}`}
                          spec={spec}
                          value={
                            pendingChanges[`${spec.path.replace('{provider}', provider.name)}`] ??
                            tool.current_values[`${spec.path.replace('{provider}', provider.name)}`]
                          }
                          onChange={(value) =>
                            handleFieldChange(spec.path.replace('{provider}', provider.name), value)
                          }
                          disabled={saving}
                          providerName={provider.name}
                        />
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

/**
 * DynamicToolsConfig - Container component for all tool configurations
 */
export const DynamicToolsConfig: React.FC = () => {
  const { t } = useTranslation('app');
  const [tools, setTools] = useState<ToolConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTools = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await toolsApi.listWithConfig();
      setTools(response.tools || []);
    } catch (err: any) {
      const errorMessage = err?.message || t('settings.errorUnknown');
      setError(t('settings.loadToolsFailed', { message: errorMessage }));
      toast.error(t('settings.loadToolsFailed', { message: errorMessage }));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTools();
  }, []);

  const handleUpdateConfig = async (toolName: string, updates: Record<string, any>) => {
    setSaving(true);
    try {
      await toolsApi.updateToolConfig(toolName, { updates });
      // Refresh tools to get updated values
      await fetchTools();
      return true;
    } catch (err: any) {
      toast.error(t('settings.toolConfigSaveFailed', { message: err?.message }));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateEnabled = async (toolName: string, enabled: boolean) => {
    setSaving(true);
    try {
      await toolsApi.updateToolConfig(toolName, { updates: {}, enabled });
      toast.success(
        enabled
          ? t('settings.toolEnabled', { tool: toolName })
          : t('settings.toolDisabled', { tool: toolName })
      );
      // Update local state immediately
      setTools((prev) =>
        prev.map((tool) =>
          tool.name === toolName ? { ...tool, enabled } : tool
        )
      );
    } catch (err: any) {
      toast.error(t('settings.toolToggleFailed', { message: err?.message }));
    } finally {
      setSaving(false);
    }
  };

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
          onUpdateConfig={handleUpdateConfig}
          onUpdateEnabled={handleUpdateEnabled}
          saving={saving}
        />
      ))}
    </div>
  );
};

export default DynamicToolsConfig;
