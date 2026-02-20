import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Download, RefreshCw, Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
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
  const [config, setConfig] = useState<SystemConfig>(DEFAULT_SYSTEM_CONFIG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState('preferences');
  const [downloadModel, setDownloadModel] = useState('bge-m3');
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [downloadStatus, setDownloadStatus] = useState<'not_downloaded' | 'downloading' | 'ready'>('not_downloaded');
  const [installedModels, setInstalledModels] = useState<string[]>([]);

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
      toast.error(`加载配置失败: ${error?.message || '未知错误'}`);
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
      toast.success('配置保存成功');
      await fetchConfig();
    } catch (error: any) {
      toast.error(`保存配置失败: ${error?.message || '未知错误'}`);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    const confirmed = window.confirm('确定要重置所有配置为默认值吗？');
    if (!confirmed) return;
    try {
      setLoading(true);
      await configApi.reset();
      toast.success('配置已重置为默认值');
      await fetchConfig();
    } catch (error: any) {
      toast.error(`重置配置失败: ${error?.message || '未知错误'}`);
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
      toast.error(error?.message || '启动下载失败');
      return;
    }

    const timer = window.setInterval(async () => {
      try {
        const status = await memoryApi.getModelStatus(downloadModel);
        setDownloadProgress(status.data?.progress || 0);
        setDownloadStatus(status.data?.status || 'not_downloaded');
        if (status.data?.status === 'ready') {
          window.clearInterval(timer);
          toast.success('模型已就绪');
          await fetchInstalledModels();
        }
      } catch {
        window.clearInterval(timer);
      }
    }, 800);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="flex items-center gap-2 text-muted-foreground">
          <LoadingSpinner />
          <span className="text-sm">加载配置中...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-6">
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>系统配置</CardTitle>
            <CardDescription>所有配置都可在此集中管理</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={fetchConfig}>
              <RefreshCw className="mr-2 h-4 w-4" />
              刷新
            </Button>
            <Button variant="destructive" onClick={handleReset}>
              重置为默认
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              <Save className="mr-2 h-4 w-4" />
              {saving ? '保存中...' : '保存全部'}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="mb-4 h-auto w-full justify-start overflow-auto">
              <TabsTrigger value="preferences">偏好</TabsTrigger>
              <TabsTrigger value="llm">LLM</TabsTrigger>
              <TabsTrigger value="personality">人格</TabsTrigger>
              <TabsTrigger value="memory">记忆</TabsTrigger>
              <TabsTrigger value="tools">工具</TabsTrigger>
              <TabsTrigger value="system">系统</TabsTrigger>
            </TabsList>

            <TabsContent value="preferences" className="grid gap-4 md:grid-cols-2">
              <SelectField
                label="界面语言"
                value={config.preferences.language}
                options={[
                  { label: '中文（简体）', value: 'zh' },
                  { label: 'English', value: 'en' },
                ]}
                onChange={(value) => patchConfig((draft) => {
                  draft.preferences.language = value as SystemConfig['preferences']['language'];
                })}
              />
              <SelectField
                label="用户模式"
                value={config.preferences.user_mode || 'quick'}
                options={[
                  { label: '快速模式', value: 'quick' },
                  { label: '专家模式', value: 'expert' },
                ]}
                onChange={(value) => patchConfig((draft) => {
                  draft.preferences.user_mode = value as NonNullable<SystemConfig['preferences']['user_mode']>;
                })}
              />
            </TabsContent>

            <TabsContent value="llm" className="grid gap-4 md:grid-cols-2">
              <SelectField
                label="提供商"
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
                <span className="text-sm font-medium">模型名称</span>
                <Input
                  value={config.llm.model}
                  onChange={(event) => patchConfig((draft) => {
                    draft.llm.model = event.target.value;
                  })}
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm font-medium">API Key</span>
                <Input
                  type="password"
                  value={config.llm.api_key || ''}
                  onChange={(event) => patchConfig((draft) => {
                    draft.llm.api_key = event.target.value;
                  })}
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm font-medium">Base URL</span>
                <Input
                  value={config.llm.base_url || ''}
                  onChange={(event) => patchConfig((draft) => {
                    draft.llm.base_url = event.target.value;
                  })}
                />
              </label>
            </TabsContent>

            <TabsContent value="personality" className="grid gap-4 md:grid-cols-2">
              <label className="space-y-2">
                <span className="text-sm font-medium">预设人格</span>
                <Input
                  value={config.personality.preset || ''}
                  onChange={(event) => patchConfig((draft) => {
                    draft.personality.preset = event.target.value;
                  })}
                />
              </label>
              <SelectField
                label="语调"
                value={config.personality.tone || 'casual'}
                options={[
                  { label: '随意', value: 'casual' },
                  { label: '正式', value: 'formal' },
                ]}
                onChange={(value) => patchConfig((draft) => {
                  draft.personality.tone = value as NonNullable<SystemConfig['personality']['tone']>;
                })}
              />
              <label className="space-y-2 md:col-span-2">
                <span className="text-sm font-medium">自定义提示词</span>
                <Textarea
                  rows={5}
                  value={config.personality.custom_prompt || ''}
                  onChange={(event) => patchConfig((draft) => {
                    draft.personality.custom_prompt = event.target.value;
                  })}
                />
              </label>
            </TabsContent>

            <TabsContent value="memory" className="space-y-4">
              <div className="grid gap-3 md:grid-cols-2">
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">L1 启用</span>
                  <Switch
                    checked={config.memory_layers.L1.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.memory_layers.L1.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">L2 启用</span>
                  <Switch
                    checked={config.memory_layers.L2.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.memory_layers.L2.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">L3 启用</span>
                  <Switch
                    checked={config.memory_layers.L3.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.memory_layers.L3.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">L4 启用</span>
                  <Switch
                    checked={config.memory_layers.L4.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.memory_layers.L4.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">L5 启用</span>
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
                  <CardTitle className="text-base">L3 模型下载</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <SelectField
                    label="模型"
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
                    下载模型
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
                    <span className="text-sm text-muted-foreground">已安装模型：</span>
                    {installedModels.length > 0 ? installedModels.map((model) => (
                      <Badge key={model} variant="secondary">{model}</Badge>
                    )) : <Badge variant="outline">暂无</Badge>}
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="tools" className="space-y-4">
              <div className="grid gap-3 md:grid-cols-2">
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">天气工具</span>
                  <Switch
                    checked={config.tools.builtIn.weather.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.tools.builtIn.weather.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">网页搜索</span>
                  <Switch
                    checked={config.tools.builtIn.webSearch.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.tools.builtIn.webSearch.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">网页抓取</span>
                  <Switch
                    checked={config.tools.builtIn.webFetch.enabled}
                    onCheckedChange={(checked) => patchConfig((draft) => {
                      draft.tools.builtIn.webFetch.enabled = checked;
                    })}
                  />
                </label>
                <label className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm font-medium">Playwright 渲染</span>
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
                label="循环策略"
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
                label="循环间隔（秒）"
                value={config.loop.interval}
                min={0.1}
                max={60}
                step={0.1}
                onChange={(value) => patchConfig((draft) => {
                  draft.loop.interval = value;
                })}
              />
              <SelectField
                label="消息总线后端"
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
                label="消息总线队列大小"
                value={config.message_bus.max_size}
                min={100}
                max={50000}
                onChange={(value) => patchConfig((draft) => {
                  draft.message_bus.max_size = value;
                })}
              />
              <NumberField
                label="WebSocket 端口"
                value={config.websocket.port}
                min={1024}
                max={65535}
                onChange={(value) => patchConfig((draft) => {
                  draft.websocket.port = value;
                })}
              />
              <SelectField
                label="日志级别"
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
