import React, { useEffect, useRef, useState } from 'react';
import { Upload, HelpCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from '@/components/ui/collapsible';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { AutoResizeTextarea } from '@/components/ui/auto-resize-textarea';
import { normalizeTransition } from '@/hooks';
import type { PersonalityConfig } from '@/api/modules/personas';

/* ── Inline help tip ── */
const HelpTip: React.FC<{ text: string }> = ({ text }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  return (
    <span ref={ref} className="relative inline-flex items-center">
      <button
        type="button"
        className="ml-1 inline-flex items-center text-muted-foreground/60 transition hover:text-muted-foreground"
        onClick={() => setOpen((v) => !v)}
        aria-label="help"
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </button>
      {open && (
        <span className="absolute bottom-full left-0 z-10 mb-1 w-56 rounded-md border border-border bg-background px-3 py-2 text-xs leading-relaxed text-foreground shadow-lg">
          {text}
        </span>
      )}
    </span>
  );
};

interface PersonalityDetailEditorProps {
  config: PersonalityConfig;
  patch: (fn: (draft: PersonalityConfig) => void) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
  onAvatarUpload?: (event: React.ChangeEvent<HTMLInputElement>) => void;
  uploadingAvatar?: boolean;
  avatarFilename?: string;
}

const PersonalityDetailEditor: React.FC<PersonalityDetailEditorProps> = ({
  config,
  patch,
  t,
  onAvatarUpload,
  uploadingAvatar = false,
  avatarFilename,
}) => {
  const [layersRevealed, setLayersRevealed] = useState(false);
  const [layersConfirmOpen, setLayersConfirmOpen] = useState(false);

  return (
    <>
      <div className="space-y-0.5 pr-1">
        {/* Basic Profile */}
        <Collapsible className="space-y-1" defaultOpen>
          <CollapsibleTrigger className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
            {t('personality.sections.basicProfile')}
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">
            <div className="grid gap-3 md:grid-cols-3">
              <label className="space-y-1.5">
                <span className="text-xs font-medium text-muted-foreground">
                  {t('personality.fields.name')}
                </span>
                <Input
                  value={config.persona_entity.basic_profile.name}
                  onChange={(e) =>
                    patch((d) => {
                      d.persona_entity.basic_profile.name = e.target.value;
                    })
                  }
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-xs font-medium text-muted-foreground">
                  {t('personality.fields.age')}
                </span>
                <Input
                  value={config.persona_entity.basic_profile.age}
                  onChange={(e) =>
                    patch((d) => {
                      d.persona_entity.basic_profile.age = e.target.value;
                    })
                  }
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-xs font-medium text-muted-foreground">
                  {t('personality.fields.gender')}
                </span>
                <Input
                  value={config.persona_entity.basic_profile.gender}
                  onChange={(e) =>
                    patch((d) => {
                      d.persona_entity.basic_profile.gender = e.target.value;
                    })
                  }
                />
              </label>
              <label className="space-y-1.5 md:col-span-3">
                <span className="text-xs font-medium text-muted-foreground">
                  {t('personality.fields.description')}
                </span>
                <Input
                  value={config.persona_entity.basic_profile.description}
                  onChange={(e) =>
                    patch((d) => {
                      d.persona_entity.basic_profile.description = e.target.value;
                    })
                  }
                />
              </label>
              {onAvatarUpload && (
                <label className="space-y-1.5 md:col-span-3">
                  <span className="text-xs font-medium text-muted-foreground">
                    {t('personality.fields.avatar')}
                  </span>
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
                      onClick={() => {
                        const node = document.getElementById(
                          'personality-detail-avatar-upload'
                        ) as HTMLInputElement | null;
                        node?.click();
                      }}
                    >
                      <Upload className="h-4 w-4" />
                      {uploadingAvatar
                        ? t('personality.actions.uploadingAvatar')
                        : t('personality.actions.uploadAvatar')}
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      {avatarFilename || t('personality.noAvatar')}
                    </span>
                  </div>
                </label>
              )}
              <label className="space-y-1.5 md:col-span-3">
                <span className="text-xs font-medium text-muted-foreground">
                  {t('personality.fields.occupation')}
                </span>
                <Input
                  value={config.persona_entity.basic_profile.occupation}
                  onChange={(e) =>
                    patch((d) => {
                      d.persona_entity.basic_profile.occupation = e.target.value;
                    })
                  }
                />
              </label>
            </div>
          </CollapsibleContent>
        </Collapsible>

        {/* Core Identity */}
        <Collapsible className="space-y-1" defaultOpen>
          <CollapsibleTrigger className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
            {t('personality.sections.coreIdentity')}
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">
            <div className="grid gap-3">
              <label className="space-y-1.5">
                <span className="text-xs font-medium text-muted-foreground">
                  {t('personality.fields.innerNarrative')}
                </span>
                <AutoResizeTextarea
                  value={config.persona_entity.core_identity.inner_narrative}
                  minHeight={120}
                  className="w-full"
                  onChange={(e) =>
                    patch((d) => {
                      d.persona_entity.core_identity.inner_narrative = e.target.value;
                    })
                  }
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-xs font-medium text-muted-foreground">
                  {t('personality.fields.languageFingerprint')}
                </span>
                <AutoResizeTextarea
                  value={config.persona_entity.core_identity.language_fingerprint}
                  minHeight={80}
                  className="w-full"
                  onChange={(e) =>
                    patch((d) => {
                      d.persona_entity.core_identity.language_fingerprint = e.target.value;
                    })
                  }
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-xs font-medium text-muted-foreground">
                  {t('personality.fields.attentionBias')}
                </span>
                <AutoResizeTextarea
                  value={config.persona_entity.core_identity.attention_bias}
                  minHeight={60}
                  className="w-full"
                  onChange={(e) =>
                    patch((d) => {
                      d.persona_entity.core_identity.attention_bias = e.target.value;
                    })
                  }
                />
              </label>
            </div>
          </CollapsibleContent>
        </Collapsible>

        {/* Appearance Prompt */}
        <Collapsible className="space-y-1">
          <CollapsibleTrigger className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
            {t('personality.sections.appearance')}
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                {t('personality.fields.appearancePrompt')}
              </span>
              <AutoResizeTextarea
                value={config.appearance_prompt}
                className="w-full"
                onChange={(e) =>
                  patch((d) => {
                    d.appearance_prompt = e.target.value;
                  })
                }
              />
            </label>
          </CollapsibleContent>
        </Collapsible>

        {/* State Transition Protocol */}
        <Collapsible className="space-y-1">
          <CollapsibleTrigger className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
            {t('personality.sections.stateTransitionProtocol')}
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">
            <div className="space-y-3">
              {config.state_transition_protocol.map((item, index) => (
                <div key={index} className="rounded-md border border-border/70 p-2">
                  <div className="grid gap-2">
                    <label className="space-y-1">
                      <span className="text-xs text-muted-foreground">
                        {t('personality.fields.triggerCondition')}
                      </span>
                      <Input
                        value={item.trigger_condition}
                        onChange={(e) =>
                          patch((d) => {
                            d.state_transition_protocol[index] = normalizeTransition({
                              ...d.state_transition_protocol[index],
                              trigger_condition: e.target.value,
                            });
                          })
                        }
                      />
                    </label>
                    <label className="space-y-1">
                      <span className="text-xs text-muted-foreground">
                        {t('personality.fields.targetStateName')}
                      </span>
                      <Input
                        value={item.target_state_name}
                        onChange={(e) =>
                          patch((d) => {
                            d.state_transition_protocol[index] = normalizeTransition({
                              ...d.state_transition_protocol[index],
                              target_state_name: e.target.value,
                            });
                          })
                        }
                      />
                    </label>
                    <label className="space-y-1">
                      <span className="text-xs text-muted-foreground">
                        {t('personality.fields.behaviorShift')}
                      </span>
                      <AutoResizeTextarea
                        value={item.behavior_shift}
                        minHeight={96}
                        className="w-full"
                        onChange={(e) =>
                          patch((d) => {
                            d.state_transition_protocol[index] = normalizeTransition({
                              ...d.state_transition_protocol[index],
                              behavior_shift: e.target.value,
                            });
                          })
                        }
                      />
                    </label>
                    <div className="flex justify-end">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          patch((d) => {
                            if (d.state_transition_protocol.length === 1) return;
                            d.state_transition_protocol.splice(index, 1);
                          })
                        }
                        disabled={config.state_transition_protocol.length === 1}
                      >
                        {t('personality.actions.removeTransition')}
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  patch((d) => {
                    d.state_transition_protocol.push(normalizeTransition({}));
                  })
                }
              >
                {t('personality.actions.addTransition')}
              </Button>
            </div>
          </CollapsibleContent>
        </Collapsible>

        {/* Persona Layers — hidden behind confirmation; hide "surface" sentinel layer */}
        {(config.persona_layers ?? []).some((l) => l.layer_id !== 'surface') && (
        <Collapsible className="space-y-1">
          <CollapsibleTrigger className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
            {t('personality.sections.personaLayers')}
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">
            {!layersRevealed ? (
              <button
                type="button"
                onClick={() => setLayersConfirmOpen(true)}
                className="w-full rounded-xl border border-dashed border-border/60 bg-muted/20 px-4 py-6 text-center text-sm text-muted-foreground transition hover:border-primary/40 hover:bg-muted/40 hover:text-foreground"
              >
                {t('personality.actions.viewLayersTitle')}
              </button>
            ) : (
              <div className="space-y-4">
                {(config.persona_layers ?? [])
                  .map((layer, index) => ({ layer, index }))
                  .filter(({ layer }) => layer.layer_id !== 'surface')
                  .map(({ layer, index }) => (
                  <div
                    key={`${index}-${layer.layer_id}`}
                    className="rounded-lg border border-border bg-muted/10 shadow-sm"
                  >
                    {/* ── Layer header ── */}
                    <div className="flex items-center justify-between border-b border-border/50 px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-muted-foreground">
                          {t('personality.fields.layerId')}
                          <HelpTip text={t('personality.help.layerId')} />
                        </span>
                        <Input
                          className="h-7 w-40 text-sm"
                          value={layer.layer_id}
                          onChange={(e) =>
                            patch((d) => {
                              d.persona_layers[index].layer_id = e.target.value;
                            })
                          }
                        />
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs text-muted-foreground hover:text-destructive"
                        onClick={() =>
                          patch((d) => {
                            d.persona_layers.splice(index, 1);
                          })
                        }
                      >
                        {t('personality.actions.removeLayer')}
                      </Button>
                    </div>

                    <div className="space-y-4 p-3">
                      {/* ── Unlock Condition ── */}
                      <fieldset className="space-y-2">
                        <legend className="text-xs font-medium text-muted-foreground">
                          {t('personality.fields.unlockCondition')}
                          <HelpTip text={t('personality.help.unlockCondition')} />
                        </legend>
                        <div className="grid gap-2 md:grid-cols-3">
                          <label className="space-y-1">
                            <span className="text-xs text-muted-foreground">
                              {t('personality.fields.trustLevelGte')}
                              <HelpTip text={t('personality.help.trustLevelGte')} />
                            </span>
                            <Input
                              type="number"
                              min={0}
                              max={1}
                              step={0.05}
                              value={(layer.unlock_condition?.trust_level_gte as number) ?? ''}
                              placeholder="0.0 – 1.0"
                              onChange={(e) =>
                                patch((d) => {
                                  if (!d.persona_layers[index].unlock_condition)
                                    d.persona_layers[index].unlock_condition = {};
                                  const v = e.target.value;
                                  if (v === '') {
                                    delete d.persona_layers[index].unlock_condition!.trust_level_gte;
                                  } else {
                                    d.persona_layers[index].unlock_condition!.trust_level_gte = parseFloat(v);
                                  }
                                })
                              }
                            />
                          </label>
                          <label className="space-y-1">
                            <span className="text-xs text-muted-foreground">
                              {t('personality.fields.interactionCountGte')}
                              <HelpTip text={t('personality.help.interactionCountGte')} />
                            </span>
                            <Input
                              type="number"
                              min={0}
                              step={1}
                              value={(layer.unlock_condition?.interaction_count_gte as number) ?? ''}
                              placeholder="0"
                              onChange={(e) =>
                                patch((d) => {
                                  if (!d.persona_layers[index].unlock_condition)
                                    d.persona_layers[index].unlock_condition = {};
                                  const v = e.target.value;
                                  if (v === '') {
                                    delete d.persona_layers[index].unlock_condition!.interaction_count_gte;
                                  } else {
                                    d.persona_layers[index].unlock_condition!.interaction_count_gte = parseInt(v, 10);
                                  }
                                })
                              }
                            />
                          </label>
                          <label className="space-y-1">
                            <span className="text-xs text-muted-foreground">
                              {t('personality.fields.milestoneRequired')}
                              <HelpTip text={t('personality.help.milestoneRequired')} />
                            </span>
                            <Input
                              value={(layer.unlock_condition?.milestone_required as string) ?? ''}
                              placeholder={t('personality.fields.milestoneRequiredPlaceholder')}
                              onChange={(e) =>
                                patch((d) => {
                                  if (!d.persona_layers[index].unlock_condition)
                                    d.persona_layers[index].unlock_condition = {};
                                  const v = e.target.value;
                                  if (v === '') {
                                    delete d.persona_layers[index].unlock_condition!.milestone_required;
                                  } else {
                                    d.persona_layers[index].unlock_condition!.milestone_required = v;
                                  }
                                })
                              }
                            />
                          </label>
                        </div>
                      </fieldset>

                      {/* Persona Override — dynamic key-value pairs */}
                      <fieldset className="space-y-2">
                        <legend className="text-xs font-medium text-muted-foreground">
                          {t('personality.fields.personaOverride')}
                          <HelpTip text={t('personality.help.personaOverride')} />
                        </legend>
                        {Object.entries(layer.persona_override ?? {}).map(
                          ([key, value], kvIdx) => (
                            <div key={kvIdx} className="flex items-start gap-2">
                              <Input
                                className="w-1/3 shrink-0"
                                value={key}
                                placeholder={t('personality.fields.overrideKeyPlaceholder')}
                                onChange={(e) =>
                                  patch((d) => {
                                    const entries = Object.entries(
                                      d.persona_layers[index].persona_override ?? {}
                                    );
                                    if (entries[kvIdx]) entries[kvIdx][0] = e.target.value;
                                    d.persona_layers[index].persona_override =
                                      Object.fromEntries(entries);
                                  })
                                }
                              />
                              <AutoResizeTextarea
                                className="w-full"
                                value={value}
                                onChange={(e) =>
                                  patch((d) => {
                                    if (!d.persona_layers[index].persona_override)
                                      d.persona_layers[index].persona_override = {};
                                    d.persona_layers[index].persona_override![key] =
                                      e.target.value;
                                  })
                                }
                              />
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="shrink-0 text-muted-foreground"
                                onClick={() =>
                                  patch((d) => {
                                    const obj = { ...(d.persona_layers[index].persona_override ?? {}) };
                                    delete obj[key];
                                    d.persona_layers[index].persona_override =
                                      Object.keys(obj).length > 0 ? obj : null;
                                  })
                                }
                              >
                                ×
                              </Button>
                            </div>
                          )
                        )}
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            patch((d) => {
                              if (!d.persona_layers[index].persona_override)
                                d.persona_layers[index].persona_override = {};
                              d.persona_layers[index].persona_override![
                                `key_${Object.keys(d.persona_layers[index].persona_override!).length}`
                              ] = '';
                            })
                          }
                        >
                          {t('personality.actions.addOverride')}
                        </Button>
                      </fieldset>

                      <label className="space-y-1">
                        <span className="text-xs text-muted-foreground">
                          {t('personality.fields.behaviorHints')}
                          <HelpTip text={t('personality.help.behaviorHints')} />
                        </span>
                        <AutoResizeTextarea
                          className="w-full"
                          value={layer.behavior_hints?.join('\n') ?? ''}
                          onChange={(e) =>
                            patch((d) => {
                              const val = e.target.value;
                              d.persona_layers[index].behavior_hints = val
                                ? val.split('\n')
                                : null;
                            })
                          }
                        />
                      </label>
                    </div>
                  </div>
                ))}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    patch((d) => {
                      if (!d.persona_layers) d.persona_layers = [];
                      d.persona_layers.push({
                        layer_id: '',
                        unlock_condition: null,
                        persona_override: null,
                        behavior_hints: null,
                      });
                    })
                  }
                >
                  {t('personality.actions.addLayer')}
                </Button>
              </div>
            )}
          </CollapsibleContent>
        </Collapsible>
        )}
      </div>

      {/* Layers reveal confirmation dialog */}
      <Dialog open={layersConfirmOpen} onOpenChange={setLayersConfirmOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('personality.actions.viewLayersTitle')}</DialogTitle>
            <DialogDescription>
              {t('personality.actions.viewLayersConfirm')}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setLayersConfirmOpen(false)}
            >
              {t('personality.cancel')}
            </Button>
            <Button
              type="button"
              onClick={() => {
                setLayersRevealed(true);
                setLayersConfirmOpen(false);
              }}
            >
              {t('personality.actions.viewLayersReveal')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default PersonalityDetailEditor;
