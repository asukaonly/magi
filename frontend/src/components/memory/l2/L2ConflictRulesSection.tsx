import React, { useState } from 'react';
import { GitMerge } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  type L2GraphConflictRule,
  type L2GraphConflictRulePayload,
} from '@/api/modules/memory';
import type { MemoryTranslateFn } from '../l2KnowledgeModel';
import { InfoCard, PANEL_CARD_CLASS, SOFT_PANEL_CLASS } from './L2Primitives';

interface L2ConflictRulesSectionProps {
  actionLoading: boolean;
  conflictRules: L2GraphConflictRule[];
  onUpsertGraphConflictRule: (payload: L2GraphConflictRulePayload) => Promise<void>;
  t: MemoryTranslateFn;
}

const defaultRuleState: L2GraphConflictRulePayload = {
  predicate: '',
  opposite_predicates: [],
  opposite_resolution: 'mark_deprecated',
  exclusive_group: '',
  exclusive_scope: 'same_subject',
  exclusive_resolution: 'mark_deprecated',
};

export const L2ConflictRulesSection: React.FC<L2ConflictRulesSectionProps> = ({
  actionLoading,
  conflictRules,
  onUpsertGraphConflictRule,
  t,
}) => {
  const [ruleForm, setRuleForm] = useState<L2GraphConflictRulePayload>(defaultRuleState);
  const [ruleOppositesText, setRuleOppositesText] = useState('');

  const handleRuleSave = async () => {
    if (!ruleForm.predicate.trim()) {
      return;
    }
    await onUpsertGraphConflictRule({
      predicate: ruleForm.predicate.trim(),
      opposite_predicates: ruleOppositesText
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
      opposite_resolution: ruleForm.opposite_resolution,
      exclusive_group: ruleForm.exclusive_group?.trim() || null,
      exclusive_scope: ruleForm.exclusive_scope ?? 'same_subject',
      exclusive_resolution: ruleForm.exclusive_resolution,
    });
    setRuleForm(defaultRuleState);
    setRuleOppositesText('');
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[0.96fr_1.04fr]">
      <InfoCard
        icon={<GitMerge className="h-5 w-5" />}
        title={t('memory.l2.lab.conflictRules')}
        emptyText={t('memory.l2.lab.noConflictRules')}
      >
        {conflictRules.map((rule) => (
          <div key={rule.predicate} className={SOFT_PANEL_CLASS}>
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-[hsl(var(--memory-title))]">{rule.predicate}</span>
              <Badge variant="outline">{rule.exclusive_group || t('memory.l2.lab.noExclusiveGroup')}</Badge>
            </div>
            <div className="mt-2 text-[hsl(var(--memory-body))]">
              {rule.opposite_predicates.length > 0
                ? rule.opposite_predicates.join(', ')
                : t('memory.l2.lab.noOpposites')}
            </div>
          </div>
        ))}
      </InfoCard>

      <Card className={PANEL_CARD_CLASS}>
        <CardHeader>
          <CardTitle className="text-base text-[hsl(var(--memory-title))]">{t('memory.l2.lab.ruleEditorTitle')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input
            value={ruleForm.predicate}
            onChange={(event) => setRuleForm((current) => ({ ...current, predicate: event.target.value }))}
            placeholder={t('memory.l2.lab.rulePredicatePlaceholder')}
          />
          <Input
            value={ruleOppositesText}
            onChange={(event) => setRuleOppositesText(event.target.value)}
            placeholder={t('memory.l2.lab.ruleOppositesPlaceholder')}
          />
          <Input
            value={ruleForm.exclusive_group || ''}
            onChange={(event) => setRuleForm((current) => ({ ...current, exclusive_group: event.target.value }))}
            placeholder={t('memory.l2.lab.ruleExclusiveGroupPlaceholder')}
          />
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-2">
              <label htmlFor="l2-rule-opposite-resolution" className="text-sm font-medium text-[hsl(var(--memory-title))]">
                {t('memory.l2.lab.ruleOppositeResolution')}
              </label>
              <select
                id="l2-rule-opposite-resolution"
                className="flex h-10 w-full rounded-xl border border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-title))] outline-none focus:border-[hsl(var(--memory-accent)/0.5)] focus:ring-2 focus:ring-[hsl(var(--memory-accent-soft)/0.7)]"
                value={ruleForm.opposite_resolution}
                onChange={(event) =>
                  setRuleForm((current) => ({ ...current, opposite_resolution: event.target.value }))
                }
              >
                <option value="mark_deprecated">{t('memory.l2.lab.ruleResolutionOptions.mark_deprecated')}</option>
                <option value="mark_conflicted">{t('memory.l2.lab.ruleResolutionOptions.mark_conflicted')}</option>
              </select>
            </div>
            <div className="space-y-2">
              <label htmlFor="l2-rule-exclusive-resolution" className="text-sm font-medium text-[hsl(var(--memory-title))]">
                {t('memory.l2.lab.ruleExclusiveResolution')}
              </label>
              <select
                id="l2-rule-exclusive-resolution"
                className="flex h-10 w-full rounded-xl border border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-title))] outline-none focus:border-[hsl(var(--memory-accent)/0.5)] focus:ring-2 focus:ring-[hsl(var(--memory-accent-soft)/0.7)]"
                value={ruleForm.exclusive_resolution}
                onChange={(event) =>
                  setRuleForm((current) => ({ ...current, exclusive_resolution: event.target.value }))
                }
              >
                <option value="mark_deprecated">{t('memory.l2.lab.ruleResolutionOptions.mark_deprecated')}</option>
                <option value="mark_conflicted">{t('memory.l2.lab.ruleResolutionOptions.mark_conflicted')}</option>
              </select>
            </div>
          </div>
          <Button onClick={handleRuleSave} disabled={actionLoading || !ruleForm.predicate.trim()}>
            <GitMerge className="mr-2 h-4 w-4" />
            {t('memory.l2.lab.saveRule')}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
};
