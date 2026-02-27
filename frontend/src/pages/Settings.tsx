import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Download, RefreshCw, Save, Trash2, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { configApi, DEFAULT_SYSTEM_CONFIG, SystemConfig } from '../api/modules/config';
import { memoryApi } from '../api/modules/memory';

type SelectOption = { label: string; value: string };

const SelectField: React.FC<{
  label: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
}> = ({ label, value, options, onChange }) => (
  <label className="space-y-2">
    <span className="text-sm font-medium">{label}</span>
    <select
      className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  </label>
);

const NumberField: React.FC<{
  label: string;
  value: number | undefined;
  min?: number;
  max?: number;
  step?: number;
  onChange: (value: number) => void;
}> = ({ label, value, min, max, step, onChange }) => (
  <label className="space-y-2">
    <span className="text-sm font-medium">{label}</span>
    <input
      className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
      type="number"
      min={min}
      max={max}
      step={step}
      value={value ?? ''}
      onChange={(event) => onChange(Number(event.target.value))}
    />
  </label>
);

export const SettingsPage: React.FC = () => {
  const { t } = useTranslation('app');
  const [config, setConfig] = useState<SystemConfig>(DEFAULT_SYSTEM_CONFIG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState('preferences');
  const [downloadModel, setDownloadModel] = useState('bge-m3');
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [downloadStatus, setDownloadStatus] = useState<'not_downloaded' | 'downloading' | 'ready'>('not_downloaded');
  const [installedModels, setInstalledModels] = useState<string[]>([]);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [clearing, setClearing] = useState(false);

  useEffect(() => {
    void fetchConfig();
    void fetchInstalledModels();
  }, []);

  const patchConfig = (updater: (draft: SystemConfig) => void) => {
    setConfig((prev) => {
      const next = structuredClone(prev);
      updater(next);
      return next;
    });
  };

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const response = await configApi.get();
      setConfig(response.data || DEFAULT_SYSTEM_CONFIG);
    } catch (error: any) {
      toast.error(t('settings.loadFailed', { message: error?.message || 'unknown' }));
    } finally {
      setLoading(false);
    }
  };

  const fetchInstalledModels = async () => {
    try {
      const response = await memoryApi.listModels();
      setInstalledModels(response.data?.models || []);
    } catch {
      setInstalledModels([]);
    }
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      await configApi.update(config);
      toast.success(t('settings.saveSuccess'));
      await fetchConfig();
    } catch (error: any) {
      toast.error(t('settings.saveFailed', { message: error?.message || 'unknown' }));
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    const confirmed = window.confirm(t('settings.resetConfirm'));
    if (!confirmed) return;
    try {
      setLoading(true);
      await configApi.reset();
      toast.success(t('settings.resetSuccess'));
      await fetchConfig();
    } catch (error: any) {
      toast.error(t('settings.resetFailed', { message: error?.message || 'unknown' }));
    } finally {
      setLoading(false);
    }
  };

  const startDownload = async () => {
    try {
      const response = await memoryApi.downloadModel(downloadModel);
      setDownloadProgress(response.data?.progress || 0);
      setDownloadStatus(response.data?.status || 'not_downloaded');
    } catch (error: any) {
      toast.error(error?.message || t('settings.downloadStartFailed'));
      return;
    }

    const timer = window.setInterval(async () => {
      try {
        const status = await memoryApi.getModelStatus(downloadModel);
        setDownloadProgress(status.data?.progress || 0);
        setDownloadStatus(status.data?.status || 'not_downloaded');
        if (status.data?.status === 'ready') {
          window.clearInterval(timer);
          toast.success(t('settings.modelReady'));
          await fetchInstalledModels();
        }
      } catch {
        window.clearInterval(timer);
      }
    }, 800);
  };

  const handleClearMemory = async () => {
    setClearing(true);
    try {
      const response = await memoryApi.clearAll();
      if (response.data?.success) {
        const results = response.data.results;
        const totalCleared = Object.values(results).reduce(
          (sum: number, r: any) => sum + (r.cleared ? r.count : 0),
          0
        );
        toast.success(t('settings.memoryCleared', { count: totalCleared }));
        if (response.data.warnings && response.data.warnings.length > 0) {
          response.data.warnings.forEach((w) => console.warn(w));
        }
      }
    } catch (error: any) {
      toast.error(error?.message || t('settings.memoryClearFailed'));
    } finally {
      setClearing(false);
      setShowClearConfirm(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="flex items-center gap-2 text-muted-foreground">
          <LoadingSpinner />
          <span className="text-sm">{t('settings.loadingConfig')}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-6">
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>{t('settings.title')}</CardTitle>
            <CardDescription>{t('settings.subtitle')}</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={fetchConfig}>
              <RefreshCw className="mr-2 h-4 w-4" />
              {t('settings.refresh')}
            </Button>
            <Button variant="destructive" onClick={handleReset}>
              {t('settings.reset')}
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              <Save className="mr-2 h-4 w-4" />
              {saving ? t('settings.saving') : t('settings.saveAll')}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="mb-4 h-auto w-full justify-start overflow-auto">
              <TabsTrigger value="preferences">{t('settings.tabs.preferences')}</TabsTrigger>
              <TabsTrigger value="llm">{t('settings.tabs.llm')}</TabsTrigger>
              <TabsTrigger value="personality">{t('settings.tabs.personality')}</TabsTrigger>
              <TabsTrigger value="memory">{t('settings.tabs.memory')}</TabsTrigger>
              <TabsTrigger value="tools">{t('settings.tabs.tools')}</TabsTrigger>
              <TabsTrigger value="system">{t('settings.tabs.system')}</TabsTrigger>
            </TabsList>

            <TabsContent value="preferences" className="grid gap-4 md:grid-cols-2">
              <SelectField
                label={t('settings.fields.language')}
                value={config.preferences.language}
                options={[
                  { label: t('language.zhHans', { ns: 'onboarding' }), value: 'zh' },
                  { label: t('language.en', { ns: 'onboarding' }), value: 'en' },
                ]}
                onChange={(value) => patchConfig((draft) => {
                  draft.preferences.language = value as SystemConfig['preferences']['language'];
                })}
              />
              <SelectField
                label={t('settings.fields.userMode')}
                value={config.preferences.user_mode || 'quick'}
                options={[
                  { label: t('settings.options.quick'), value: 'quick' },
                  { label: t('settings.options.expert'), value: 'expert' },
                ]}
                onChange={(value) => patchConfig((draft) => {
                  draft.preferences.user_mode = value as NonNullable<SystemConfig['preferences']['user_mode']>;
                })}
              />
            </TabsContent>

            <TabsContent value="llm" className="grid gap-4 md:grid-cols-2">
              <SelectField
                label={t('settings.fields.provider')}
                value={config.llm.provider}
                options={[
                  { label: 'OpenAI', value: 'openai' },
                  { label: 'Anthropic', value: 'anthropic' },
                  { label: 'GLM', value: 'glm' },
                  { label: 'Custom', value: 'custom' },
                ]}
                onChange={(value) => patchConfig((draft) => {
                  draft.llm.provider = value as SystemConfig['llm']['provider'];
                })}
              />
              <label className="space-y-2">
                <span className="text-sm font-medium">{t('settings.fields.modelName')}</span>
                <Input
                  value={config.llm.model}
                  onChange={(event) => patchConfig((draft) => {
                    draft.llm.model = event.target.value;
                  })}
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm font-medium">{t('settings.fields.apiKey')}</span>
                <Input
                  type="password"
                  value={config.llm.api_key || ''}
                  onChange={(event) => patchConfig((draft) => {
                    draft.llm.api_key = event.target.value;
                  })}
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm font-medium">{t('settings.fields.baseUrl')}</span>
                <Input
                  value={config.llm.base_url || ''}
                  onChange={(event) => patchConfig((draft) => {
                    draft.llm.base_url = event.target.value;
                  })}
                />
              </label>
            </TabsContent>

            <TabsContent value="personality" className="space-y-4">
              <div className="rounded-md border p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <h3 className="font-medium">{t('settings.fields.currentPersonality')}</h3>
                    <p className="text-sm text-muted-foreground">{config.personality?.persona_entity?.basic_profile?.name || 'Default'}</p>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => window.location.href = '/personality'}>
                    {t('settings.actions.configure')}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  {config.personality?.persona_entity?.basic_profile?.occupation || ''}
                </p>
              </div>
            </TabsContent>

            <TabsContent value="memory" className="space-y-4">
              {/* 清除记忆卡片 */}
              <Card className="border-destructive/50">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base text-destructive">
                    <Trash2 className="h-4 w-4" />
                    {t('settings.fields.clearMemory')}
                  </CardTitle>
                  <CardDescription>
                    {t('settings.fields.clearMemoryDesc')}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <Button
                    variant="destructive"
                    onClick={() => setShowClearConfirm(true)}
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    {t('settings.actions.clearMemory')}
                  </Button>
                </CardContent>
              </Card>

              {/* 确认对话框 */}
              {showClearConfirm && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
                  <Card className="mx-4 max-w-md">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2 text-destructive">
                        <AlertTriangle className="h-5 w-5" />
                        {t('settings.clearConfirm.title')}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm">
                        <p className="font-medium text-destructive">{t('settings.clearConfirm.warning')}</p>
                        <ul className="mt-2 list-inside list-disc space-y-1 text-destructive/80">
                          <li>{t('settings.clearConfirm.l1')}</li>
                          <li>{t('settings.clearConfirm.l2')}</li>
                          <li>{t('settings.clearConfirm.l3')}</li>
                          <li>{t('settings.clearConfirm.l4')}</li>
                          <li>{t('settings.clearConfirm.l5')}</li>
                          <li>{t('settings.clearConfirm.chatContext')}</li>
                        </ul>
                        <p className="mt-3 font-semibold text-destructive">
                          {t('settings.clearConfirm.irreversible')}
                        </p>
                      </div>
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="outline"
                          onClick={() => setShowClearConfirm(false)}
                          disabled={clearing}
                        >
                          {t('settings.clearConfirm.cancel')}
                        </Button>
                        <Button
                          variant="destructive"
                          onClick={handleClearMemory}
                          disabled={clearing}
                        >
                          {clearing ? t('settings.clearConfirm.clearing') : t('settings.clearConfirm.confirm')}
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              )}

              <div className="grid gap-3 md:grid-cols-2">
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">{t('settings.fields.l1Enabled')}</span>
                  <Switch
                    checked={config.memory_layers.L1.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.memory_layers.L1.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">{t('settings.fields.l2Enabled')}</span>
                  <Switch
                    checked={config.memory_layers.L2.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.memory_layers.L2.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">{t('settings.fields.l3Enabled')}</span>
                  <Switch
                    checked={config.memory_layers.L3.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.memory_layers.L3.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">{t('settings.fields.l4Enabled')}</span>
                  <Switch
                    checked={config.memory_layers.L4.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.memory_layers.L4.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">{t('settings.fields.l5Enabled')}</span>
                  <Switch
                    checked={config.memory_layers.L5.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.memory_layers.L5.enabled = checked;
                    })}
                  />
                </label>
              </div>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">{t('settings.fields.l3ModelDownload')}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <SelectField
                    label={t('settings.fields.model')}
                    value={downloadModel}
                    options={[
                      { label: 'bge-m3', value: 'bge-m3' },
                      { label: 'nomic-embed-text', value: 'nomic-embed-text' },
                      { label: 'text-embedding-3-large', value: 'text-embedding-3-large' },
                    ]}
                    onChange={setDownloadModel}
                  />
                  <Button variant="outline" onClick={startDownload}>
                    <Download className="mr-2 h-4 w-4" />
                    {t('settings.fields.downloadModel')}
                  </Button>
                  <div className="space-y-1">
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div className="h-full bg-primary transition-all" style={{ width: `${downloadProgress}%` }} />
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {downloadStatus} · {downloadProgress}%
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <span className="text-sm text-muted-foreground">{t('settings.fields.installedModels')}</span>
                    {installedModels.length > 0 ? installedModels.map((model) => (
                      <Badge key={model} variant="secondary">{model}</Badge>
                    )) : <Badge variant="outline">{t('settings.fields.none')}</Badge>}
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="tools" className="space-y-4">
              <div className="grid gap-3 md:grid-cols-2">
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">{t('settings.fields.weatherTool')}</span>
                  <Switch
                    checked={config.tools.builtIn.weather.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.tools.builtIn.weather.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">{t('settings.fields.webSearchTool')}</span>
                  <Switch
                    checked={config.tools.builtIn.webSearch.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.tools.builtIn.webSearch.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">{t('settings.fields.webFetchTool')}</span>
                  <Switch
                    checked={config.tools.builtIn.webFetch.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.tools.builtIn.webFetch.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">{t('settings.fields.playwrightRendering')}</span>
                  <Switch
                    checked={config.tools.builtIn.webFetch.usePlaywright}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.tools.builtIn.webFetch.usePlaywright = checked;
                    })}
                  />
                </label>
              </div>
            </TabsContent>

            <TabsContent value="system" className="grid gap-4 md:grid-cols-2">
              <SelectField
                label={t('settings.fields.loopStrategy')}
                value={config.loop.strategy}
                options={[
                  { label: 'STEP', value: 'step' },
                  { label: 'WAVE', value: 'wave' },
                  { label: 'CONTINUOUS', value: 'continuous' },
                ]}
                onChange={(value) => patchConfig((draft) => {
                  draft.loop.strategy = value as SystemConfig['loop']['strategy'];
                })}
              />
              <NumberField
                label={t('settings.fields.loopInterval')}
                value={config.loop.interval}
                min={0.1}
                max={60}
                step={0.1}
                onChange={(value) => patchConfig((draft) => {
                  draft.loop.interval = value;
                })}
              />
              <SelectField
                label={t('settings.fields.busBackend')}
                value={config.message_bus.backend}
                options={[
                  { label: 'memory', value: 'memory' },
                  { label: 'sqlite', value: 'sqlite' },
                  { label: 'redis', value: 'redis' },
                ]}
                onChange={(value) => patchConfig((draft) => {
                  draft.message_bus.backend = value as SystemConfig['message_bus']['backend'];
                })}
              />
              <NumberField
                label={t('settings.fields.busQueueSize')}
                value={config.message_bus.max_size}
                min={100}
                max={50000}
                onChange={(value) => patchConfig((draft) => {
                  draft.message_bus.max_size = value;
                })}
              />
              <NumberField
                label={t('settings.fields.wsPort')}
                value={config.websocket.port}
                min={1024}
                max={65535}
                onChange={(value) => patchConfig((draft) => {
                  draft.websocket.port = value;
                })}
              />
              <SelectField
                label={t('settings.fields.logLevel')}
                value={config.log.level}
                options={[
                  { label: 'DEBUG', value: 'DEBUG' },
                  { label: 'INFO', value: 'INFO' },
                  { label: 'WARNING', value: 'WARNING' },
                  { label: 'ERROR', value: 'ERROR' },
                ]}
                onChange={(value) => patchConfig((draft) => {
                  draft.log.level = value as SystemConfig['log']['level'];
                })}
              />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
};
