import React, { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, Sparkles, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { SelectField } from './fields';
import { DEFAULT_PERSONALITY_CONFIG, personalityApi, personalitiesApi, PersonalityPreset } from '../../api';

interface PersonalityFormProps {
  quickMode?: boolean;
  language?: 'zh' | 'en';
}

export const PersonalityForm: React.FC<PersonalityFormProps> = ({ quickMode = false, language = 'zh' }) => {
  const { t } = useTranslation('onboarding');
  const [presets, setPresets] = useState<PersonalityPreset[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [customName, setCustomName] = useState('');
  const [customSummary, setCustomSummary] = useState('');
  const [oneLiner, setOneLiner] = useState('');
  const [selectedCard, setSelectedCard] = useState<string | null>(null);

  useEffect(() => {
    const loadPresets = async () => {
      try {
        const response = await personalitiesApi.list(language);
        setPresets(response.data || []);
      } catch (error) {
        setPresets([]);
      }
    };
    void loadPresets();
  }, [language]);

  const avatarFor = (item: PersonalityPreset): string => {
    const map: Record<string, string> = {
      assistant: '🤖',
      analyst: '🧠',
      teacher: '🧑‍🏫',
      coder: '💻',
      writer: '✍️',
      default: '✨',
    };
    return map[item.id] || item.name.trim().charAt(0).toUpperCase() || '✨';
  };

  return (
    <>
      <Form.Item label={t('personality.presetLabel')}>
        <Form.Item noStyle shouldUpdate>
          {({
            getFieldValue,
            setFieldValue,
          }: {
            getFieldValue: (name: any) => any;
            setFieldValue: (name: any, value: any) => void;
          }) => {
            const selectedPreset = getFieldValue(['personality', 'preset']);
            const selectedTone = getFieldValue(['personality', 'tone']) || 'casual';
            const showCustomSection = Boolean(selectedPreset) || selectedCard === '__blank__';

            return (
              <div className="space-y-3">
                <div className="grid gap-3 md:grid-cols-2">
                  {presets.map((item) => {
                    const active = selectedPreset === item.id;
                    return (
                      <React.Fragment key={item.id}>
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedCard(item.id);
                            setFieldValue(['personality', 'preset'], item.id);
                            if (!getFieldValue(['personality', 'custom_prompt'])) {
                              setFieldValue(['personality', 'custom_prompt'], item.prompt || '');
                            }
                          }}
                          className={cn(
                            'rounded-xl border bg-background p-3 text-left transition',
                            active ? 'border-teal-600 bg-teal-600/5 shadow-sm' : 'border-border hover:border-teal-600/40'
                          )}
                        >
                          <div className="mb-2 flex items-center gap-2">
                            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted text-sm">
                              {avatarFor(item)}
                            </div>
                            <div>
                              <p className="text-sm font-semibold">{item.name}</p>
                              <p className="text-xs text-muted-foreground">{item.id}</p>
                            </div>
                          </div>
                          <p className="line-clamp-2 text-xs text-muted-foreground">{item.description}</p>
                        </button>

                        {item.id === 'default' && (
                          <button
                            type="button"
                            onClick={() => {
                              setSelectedCard('__blank__');
                              setFieldValue(['personality', 'preset'], undefined);
                              setFieldValue(['personality', 'custom_prompt'], '');
                              setFieldValue(['personality', 'tone'], 'casual');
                              setCustomName('');
                              setCustomSummary('');
                              setOneLiner('');
                            }}
                            className={cn(
                              'rounded-xl border border-dashed bg-background p-3 text-left transition',
                              selectedCard === '__blank__'
                                ? 'border-teal-600 bg-teal-600/5 shadow-sm'
                                : 'border-border hover:border-teal-600/40'
                            )}
                          >
                            <div className="mb-2 flex items-center gap-2">
                              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted text-sm">
                                +
                              </div>
                              <div>
                                <p className="text-sm font-semibold">{t('personality.blankCardTitle')}</p>
                                <p className="text-xs text-muted-foreground">{t('personality.blankCardTag')}</p>
                              </div>
                            </div>
                            <p className="line-clamp-2 text-xs text-muted-foreground">{t('personality.blankCardDesc')}</p>
                          </button>
                        )}
                      </React.Fragment>
                    );
                  })}
                </div>

                {showCustomSection && (
                  <>
                    <div className="rounded-xl border border-border bg-muted/20 p-3">
                      <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                        <Sparkles className="h-4 w-4 text-teal-600" />
                        {t('personality.oneLinerLabel')}
                      </div>
                      <div className="flex flex-col gap-2 md:flex-row">
                        <Input
                          value={oneLiner}
                          onChange={(event) => setOneLiner(event.target.value)}
                          placeholder={t('personality.oneLinerPlaceholder')}
                        />
                        <Button
                          type="button"
                          disabled={generating}
                          onClick={async () => {
                            if (!oneLiner.trim()) return;
                            setGenerating(true);
                            try {
                              const generated = await personalityApi.generate({
                                description: oneLiner.trim(),
                                target_language: language === 'zh' ? 'Chinese' : 'English',
                              });
                              const data = (generated.data || {}) as any;
                              const generatedName = data?.persona_entity?.basic_profile?.name || '';
                              const generatedBackstory = data?.persona_entity?.basic_profile?.core_background || '';
                              const generatedTone = data?.persona_entity?.psychological_traits?.communication_tone || '';

                              setCustomName(generatedName);
                              setCustomSummary(generatedBackstory);
                              setFieldValue(
                                ['personality', 'custom_prompt'],
                                [generatedName, generatedBackstory].filter(Boolean).join('\n')
                              );
                              if (generatedTone) {
                                const normalized = generatedTone.toLowerCase().includes('formal') ? 'formal' : 'casual';
                                setFieldValue(['personality', 'tone'], normalized);
                              }
                            } catch {
                              // Ignore generate errors and keep current values.
                            } finally {
                              setGenerating(false);
                            }
                          }}
                        >
                          {generating ? t('personality.generating') : t('personality.generateAction')}
                        </Button>
                      </div>
                    </div>

                    <div className="rounded-xl border border-border bg-background p-3">
                      <button
                        type="button"
                        onClick={() => setExpanded((prev) => !prev)}
                        className="flex w-full items-center justify-between text-left"
                      >
                        <div className="flex items-center gap-2">
                          <UserRound className="h-4 w-4 text-teal-600" />
                          <span className="text-sm font-medium">{t('personality.expandTitle')}</span>
                        </div>
                        {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                      </button>

                      {expanded && (
                        <div className="mt-3 space-y-3 border-t border-border/70 pt-3">
                          <label className="block space-y-2">
                            <span className="text-xs font-medium text-muted-foreground">{t('personality.customNameLabel')}</span>
                            <Input
                              value={customName}
                              onChange={(event) => setCustomName(event.target.value)}
                              placeholder={t('personality.customNamePlaceholder')}
                            />
                          </label>

                          <label className="block space-y-2">
                            <span className="text-xs font-medium text-muted-foreground">{t('personality.summaryLabel')}</span>
                            <Textarea
                              rows={3}
                              value={customSummary}
                              onChange={(event) => setCustomSummary(event.target.value)}
                              placeholder={t('personality.summaryPlaceholder')}
                            />
                          </label>

                          <Form.Item label={t('personality.toneLabel')} name={['personality', 'tone']}>
                            <SelectField
                              options={[
                                { label: t('personality.toneOptions.casual'), value: 'casual' },
                                { label: t('personality.toneOptions.formal'), value: 'formal' },
                              ]}
                            />
                          </Form.Item>

                          <Form.Item label={t('personality.customPromptLabel')} name={['personality', 'custom_prompt']}>
                            <Textarea rows={5} placeholder={t('personality.customPromptPlaceholder')} />
                          </Form.Item>

                          <div className="rounded-md border border-border/70 bg-muted/20 p-2 text-xs text-muted-foreground">
                            {t('personality.detailTip', {
                              tone: selectedTone === 'formal' ? t('personality.toneOptions.formal') : t('personality.toneOptions.casual'),
                            })}
                          </div>

                          <div className="flex flex-wrap gap-2">
                            <Button
                              type="button"
                              variant="outline"
                              onClick={() => {
                                const mergedPrompt = [
                                  customName ? `${t('personality.promptNamePrefix')}${customName}` : '',
                                  customSummary,
                                  getFieldValue(['personality', 'custom_prompt']) || '',
                                ]
                                  .filter(Boolean)
                                  .join('\n');
                                setFieldValue(['personality', 'custom_prompt'], mergedPrompt);
                              }}
                            >
                              {t('personality.applyDetailsAction')}
                            </Button>

                            <Button
                              type="button"
                              variant="outline"
                              onClick={async () => {
                                const prompt = getFieldValue(['personality', 'custom_prompt']) || '';
                                if (!prompt.trim()) return;
                                try {
                                  const payload = structuredClone(DEFAULT_PERSONALITY_CONFIG);
                                  payload.persona_entity.basic_profile.name = customName || payload.persona_entity.basic_profile.name;
                                  payload.persona_entity.basic_profile.core_background = customSummary || prompt;
                                  payload.persona_entity.psychological_traits.communication_tone =
                                    selectedTone === 'formal'
                                      ? 'Precise, composed, and respectful'
                                      : 'Casual, direct, and warm';
                                  const response = await personalityApi.updateWithAIName(payload);
                                  const actualName = (response.data as any)?.actual_name;
                                  if (actualName) {
                                    await personalityApi.setCurrent(actualName);
                                  }
                                } catch {
                                  // Keep onboarding form usable even when persistence fails.
                                }
                              }}
                            >
                              {t('personality.saveCustomAction')}
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            );
          }}
        </Form.Item>
      </Form.Item>

      {/* Keep this prop for call-site compatibility; both modes now share the same personality editing surface. */}
      {quickMode ? null : null}
    </>
  );
};

export default PersonalityForm;
