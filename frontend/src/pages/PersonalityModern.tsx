import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Check, Plus, RefreshCw, Sparkles, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { personalityApi, DEFAULT_PERSONALITY_CONFIG, type PersonalityConfig, type PersonalityDiff } from '../api';

interface PersonalityInfo {
  name: string;
  displayName: string;
  archetype?: string;
}

const TONE_OPTIONS = ['friendly', 'professional', 'humorous', 'serious', 'warm', 'aggressive', 'haughty', 'gentle'];
const PACING_OPTIONS = ['slow', 'moderate', 'fast', 'impatient'];
const CONFIDENCE_OPTIONS = ['High', 'Medium', 'Low'];
const EMPATHY_OPTIONS = ['High', 'Medium', 'Low', 'Selective'];
const PATIENCE_OPTIONS = ['High', 'Medium', 'Low'];
const OPINION_STRENGTH_OPTIONS = ['Objective/Neutral', 'Highly Opinionated', 'Consensus Seeking'];
const WORK_ETHIC_OPTIONS = ['Perfectionist', 'Lazy Genius', 'By-the-book', 'Chaotic'];

const PersonalityModern: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [currentName, setCurrentName] = useState('default');
  const [selectedName, setSelectedName] = useState('default');
  const [config, setConfig] = useState<PersonalityConfig>(DEFAULT_PERSONALITY_CONFIG);
  const [list, setList] = useState<PersonalityInfo[]>([
    { name: 'default', displayName: '默认人格', archetype: 'System Default' },
  ]);
  const [prompt, setPrompt] = useState('');
  const [targetLanguage, setTargetLanguage] = useState('Auto');
  const [diffs, setDiffs] = useState<PersonalityDiff[]>([]);

  const patch = (fn: (draft: PersonalityConfig) => void) => {
    setConfig((prev) => {
      const next = structuredClone(prev);
      fn(next);
      return next;
    });
  };

  const loadList = useCallback(async () => {
    try {
      const result = await personalityApi.list();
      const names = ((result.data as any)?.personalities || ['default']) as string[];
      const items: PersonalityInfo[] = [];
      for (const name of names) {
        try {
          const detail = await personalityApi.get(name);
          const meta = (detail.data as any)?.meta;
          items.push({
            name,
            displayName: meta?.name || name,
            archetype: meta?.archetype,
          });
        } catch {
          items.push({ name, displayName: name });
        }
      }
      setList(items.length ? items : [{ name: 'default', displayName: '默认人格' }]);
    } catch {
      setList([{ name: 'default', displayName: '默认人格' }]);
    }
  }, []);

  const loadCurrent = useCallback(async () => {
    try {
      const result = await personalityApi.getCurrent();
      const current = (result.data as any)?.current || 'default';
      setCurrentName(current);
      setSelectedName(current);
      return current;
    } catch {
      setCurrentName('default');
      setSelectedName('default');
      return 'default';
    }
  }, []);

  const loadOne = useCallback(async (name: string) => {
    setLoading(true);
    try {
      const result = await personalityApi.get(name);
      const data = (result.data || {}) as Partial<PersonalityConfig>;
      setConfig({
        meta: { ...DEFAULT_PERSONALITY_CONFIG.meta, ...(data.meta || {}) },
        core_identity: {
          ...DEFAULT_PERSONALITY_CONFIG.core_identity,
          ...(data.core_identity || {}),
          voice_style: {
            ...DEFAULT_PERSONALITY_CONFIG.core_identity.voice_style,
            ...(data.core_identity?.voice_style || {}),
          },
          psychological_profile: {
            ...DEFAULT_PERSONALITY_CONFIG.core_identity.psychological_profile,
            ...(data.core_identity?.psychological_profile || {}),
          },
        },
        social_protocols: { ...DEFAULT_PERSONALITY_CONFIG.social_protocols, ...(data.social_protocols || {}) },
        operational_behavior: { ...DEFAULT_PERSONALITY_CONFIG.operational_behavior, ...(data.operational_behavior || {}) },
        cached_phrases: { ...DEFAULT_PERSONALITY_CONFIG.cached_phrases, ...(data.cached_phrases || {}) },
      });
    } catch {
      toast.error('加载人格失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const init = async () => {
      const current = await loadCurrent();
      await loadList();
      await loadOne(current);
    };
    void init();
  }, [loadCurrent, loadList, loadOne]);

  const switchPersonality = async () => {
    if (selectedName === currentName) return;
    setSwitching(true);
    try {
      const response = await personalityApi.compare(currentName, selectedName);
      const nextDiffs = ((response.data as any)?.diffs || []) as PersonalityDiff[];
      setDiffs(nextDiffs);
      const ok = window.confirm(`确认切换人格：${currentName} -> ${selectedName} ?`);
      if (!ok) return;
      await personalityApi.setCurrent(selectedName);
      setCurrentName(selectedName);
      await loadOne(selectedName);
      toast.success(`已切换到 ${selectedName}`);
    } catch {
      toast.error('切换失败');
    } finally {
      setSwitching(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      if (currentName === 'default' || currentName !== config.meta.name) {
        await personalityApi.updateWithAIName(config);
      } else {
        await personalityApi.update(currentName, config);
      }
      toast.success('已保存');
      await loadList();
      await loadCurrent();
    } catch {
      toast.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const generate = async () => {
    if (!prompt.trim()) {
      toast.warning('请输入一句话描述');
      return;
    }
    setGenerating(true);
    try {
      const response = await personalityApi.generate({ description: prompt, target_language: targetLanguage });
      const data = (response.data || {}) as Partial<PersonalityConfig>;
      setConfig((prev) => {
        const next = structuredClone(prev);
        next.meta = { ...next.meta, ...(data.meta || {}) };
        next.core_identity = {
          ...next.core_identity,
          ...(data.core_identity || {}),
          voice_style: {
            ...next.core_identity.voice_style,
            ...(data.core_identity?.voice_style || {}),
          },
          psychological_profile: {
            ...next.core_identity.psychological_profile,
            ...(data.core_identity?.psychological_profile || {}),
          },
        };
        next.social_protocols = { ...next.social_protocols, ...(data.social_protocols || {}) };
        next.operational_behavior = { ...next.operational_behavior, ...(data.operational_behavior || {}) };
        next.cached_phrases = { ...next.cached_phrases, ...(data.cached_phrases || {}) };
        return next;
      });
      setPrompt('');
      toast.success('已生成草稿');
    } catch {
      toast.error('生成失败');
    } finally {
      setGenerating(false);
    }
  };

  const diffPreview = useMemo(() => diffs.slice(0, 8), [diffs]);

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <Card>
        <CardHeader>
          <CardTitle>人格配置（shadcn 原生）</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">当前生效</span>
            <Badge>{currentName}</Badge>
            <select
              className="h-10 min-w-[220px] rounded-md border border-input bg-background px-3 text-sm"
              value={selectedName}
              onChange={(event) => {
                setSelectedName(event.target.value);
                void loadOne(event.target.value);
              }}
            >
              {list.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.displayName}{item.archetype ? ` (${item.archetype})` : ''}
                </option>
              ))}
            </select>
            {selectedName !== currentName && (
              <Button onClick={switchPersonality} disabled={switching}>
                <Check className="mr-2 h-4 w-4" />
                {switching ? '切换中...' : '切换'}
              </Button>
            )}
            <Button variant="outline" onClick={() => void loadOne(selectedName)}><RefreshCw className="mr-2 h-4 w-4" />重载</Button>
            <Button variant="outline" onClick={() => {
              const name = window.prompt('新人格名称');
              if (!name) return;
              void personalityApi.updateWithAIName({ ...DEFAULT_PERSONALITY_CONFIG, meta: { ...DEFAULT_PERSONALITY_CONFIG.meta, name } }).then(loadList);
            }}><Plus className="mr-2 h-4 w-4" />新建</Button>
            <Button variant="destructive" onClick={() => {
              if (selectedName === 'default') return;
              if (window.confirm(`删除 ${selectedName} ?`)) void personalityApi.delete(selectedName).then(loadList);
            }}><Trash2 className="mr-2 h-4 w-4" />删除</Button>
          </div>

          <div className="flex gap-2">
            <Input value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="一句话描述人格用于 AI 生成" />
            <select
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={targetLanguage}
              onChange={(event) => setTargetLanguage(event.target.value)}
            >
              <option value="Auto">自动检测</option>
              <option value="Chinese">中文</option>
              <option value="English">English</option>
              <option value="Japanese">日本語</option>
            </select>
            <Button onClick={generate} disabled={generating}><Sparkles className="mr-2 h-4 w-4" />AI 生成</Button>
          </div>

          {diffPreview.length > 0 && (
            <div className="rounded-md border p-3">
              <div className="mb-2 text-sm font-medium">人格差异预览（前 8 项）</div>
              <div className="space-y-1 text-xs text-muted-foreground">
                {diffPreview.map((item) => (
                  <div key={item.field}>
                    {item.field_label}: <span className="text-red-600">{String(item.old_value)}</span> {'->'}{' '}
                    <span className="text-emerald-600">{String(item.new_value)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>基本信息</CardTitle></CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium">名字</span>
            <Input value={config.meta.name} onChange={(event) => patch((d) => { d.meta.name = event.target.value; })} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">原型</span>
            <Input value={config.meta.archetype} onChange={(event) => patch((d) => { d.meta.archetype = event.target.value; })} />
          </label>
          <label className="space-y-2 md:col-span-2">
            <span className="text-sm font-medium">背景故事</span>
            <Textarea rows={5} value={config.core_identity.backstory} onChange={(event) => patch((d) => { d.core_identity.backstory = event.target.value; })} />
          </label>
          <div className="flex items-center justify-between rounded-md border p-3 md:col-span-2">
            <span className="text-sm">启用 Emoji</span>
            <Switch checked={config.operational_behavior.use_emoji} onCheckedChange={(checked) => patch((d) => { d.operational_behavior.use_emoji = checked; })} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>声音风格与心理特征</CardTitle></CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-3">
          <label className="space-y-2">
            <span className="text-sm font-medium">语调</span>
            <select
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={config.core_identity.voice_style.tone}
              onChange={(event) => patch((d) => { d.core_identity.voice_style.tone = event.target.value; })}
            >
              {TONE_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">节奏</span>
            <select
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={config.core_identity.voice_style.pacing}
              onChange={(event) => patch((d) => { d.core_identity.voice_style.pacing = event.target.value; })}
            >
              {PACING_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">常用词（逗号分隔）</span>
            <Input
              value={config.core_identity.voice_style.keywords.join(', ')}
              onChange={(event) => patch((d) => {
                d.core_identity.voice_style.keywords = event.target.value
                  .split(',')
                  .map((item) => item.trim())
                  .filter(Boolean);
              })}
            />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">自信水平</span>
            <select
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={config.core_identity.psychological_profile.confidence_level}
              onChange={(event) => patch((d) => { d.core_identity.psychological_profile.confidence_level = event.target.value; })}
            >
              {CONFIDENCE_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">共情水平</span>
            <select
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={config.core_identity.psychological_profile.empathy_level}
              onChange={(event) => patch((d) => { d.core_identity.psychological_profile.empathy_level = event.target.value; })}
            >
              {EMPATHY_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">耐心水平</span>
            <select
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={config.core_identity.psychological_profile.patience_level}
              onChange={(event) => patch((d) => { d.core_identity.psychological_profile.patience_level = event.target.value; })}
            >
              {PATIENCE_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>社交协议</CardTitle></CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium">用户关系</span>
            <Input
              value={config.social_protocols.user_relationship}
              onChange={(event) => patch((d) => { d.social_protocols.user_relationship = event.target.value; })}
            />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">赞美反应</span>
            <Input
              value={config.social_protocols.compliment_policy}
              onChange={(event) => patch((d) => { d.social_protocols.compliment_policy = event.target.value; })}
            />
          </label>
          <label className="space-y-2 md:col-span-2">
            <span className="text-sm font-medium">批评容忍度</span>
            <Input
              value={config.social_protocols.criticism_tolerance}
              onChange={(event) => patch((d) => { d.social_protocols.criticism_tolerance = event.target.value; })}
            />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>行为策略</CardTitle></CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium">错误处理风格</span>
            <Input
              value={config.operational_behavior.error_handling_style}
              onChange={(event) => patch((d) => { d.operational_behavior.error_handling_style = event.target.value; })}
            />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">拒绝风格</span>
            <Input
              value={config.operational_behavior.refusal_style}
              onChange={(event) => patch((d) => { d.operational_behavior.refusal_style = event.target.value; })}
            />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">意见强度</span>
            <select
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={config.operational_behavior.opinion_strength}
              onChange={(event) => patch((d) => { d.operational_behavior.opinion_strength = event.target.value; })}
            >
              {OPINION_STRENGTH_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">职业道德</span>
            <select
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={config.operational_behavior.work_ethic}
              onChange={(event) => patch((d) => { d.operational_behavior.work_ethic = event.target.value; })}
            >
              {WORK_ETHIC_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <div className="flex items-center justify-between rounded-md border p-3 md:col-span-2">
            <span className="text-sm">启用 Emoji</span>
            <Switch checked={config.operational_behavior.use_emoji} onCheckedChange={(checked) => patch((d) => { d.operational_behavior.use_emoji = checked; })} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>缓存短语</CardTitle></CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium">初始化问候</span>
            <Input value={config.cached_phrases.on_init} onChange={(event) => patch((d) => { d.cached_phrases.on_init = event.target.value; })} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">唤醒问候</span>
            <Input value={config.cached_phrases.on_wake} onChange={(event) => patch((d) => { d.cached_phrases.on_wake = event.target.value; })} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">错误提示</span>
            <Input value={config.cached_phrases.on_error_generic} onChange={(event) => patch((d) => { d.cached_phrases.on_error_generic = event.target.value; })} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">成功提示</span>
            <Input value={config.cached_phrases.on_success} onChange={(event) => patch((d) => { d.cached_phrases.on_success = event.target.value; })} />
          </label>
          <label className="space-y-2 md:col-span-2">
            <span className="text-sm font-medium">切换挽留</span>
            <Input value={config.cached_phrases.on_switch_attempt} onChange={(event) => patch((d) => { d.cached_phrases.on_switch_attempt = event.target.value; })} />
          </label>
        </CardContent>
      </Card>

      <div className="flex justify-center">
        <Button onClick={save} disabled={saving || loading} size="lg">
          <Check className="mr-2 h-4 w-4" />
          {saving ? '保存中...' : '保存配置'}
        </Button>
      </div>
    </div>
  );
};

export default PersonalityModern;
