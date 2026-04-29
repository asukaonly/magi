/**
 * Dynamic Tool Configuration Components
 *
 * Renders tool configuration forms dynamically based on API-provided specs.
 */
import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronDown,
  ChevronUp,
  AlertCircle,
  CheckCircle,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { DynamicConfigField } from '@/components/config-forms/DynamicConfigField';
import { type ToolConfig } from '@/api/modules/tools';

export { DynamicConfigField } from '@/components/config-forms/DynamicConfigField';
export type { DynamicConfigSpec } from '@/components/config-forms/dynamic-config-specs';

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
