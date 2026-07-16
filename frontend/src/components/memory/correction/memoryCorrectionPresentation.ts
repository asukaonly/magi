import type { TFunction } from 'i18next';

type AppTranslation = TFunction<'app'>;

export const correctionLocale = (language?: string): string | undefined => {
  const normalized = String(language || '').trim().toLowerCase();
  if (!normalized) return undefined;
  if (normalized.startsWith('zh')) return 'zh-CN';
  if (normalized.startsWith('en')) return 'en';
  return language;
};

export const formatCorrectionTime = (value: number, locale?: string): string => {
  const timestamp = value > 10_000_000_000 ? value : value * 1000;
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(timestamp));
};

export const formatCorrectionScope = (
  scope: { all_of?: unknown } | null | undefined,
  t: AppTranslation,
  contextLabels: Readonly<Record<string, string>> = {}
): string | null => {
  if (!scope) return null;
  const allOf = Array.isArray(scope.all_of) ? scope.all_of : [];
  const entries = allOf.flatMap((condition) => {
    if (!condition || typeof condition !== 'object' || Array.isArray(condition)) return [];
    const candidate = condition as Record<string, unknown>;
    const dimension = String(candidate.dimension ?? '').trim().toLowerCase();
    const contextId = String(candidate.context_id ?? '').trim();
    if (!dimension || !contextId) return [];
    const label = scopeDimensionLabel(dimension, t);
    const contextLabel = String(contextLabels[contextId] ?? '').trim();
    return [t('memory.correction.history.scopeEntry', {
      defaultValue: '{{label}}: {{value}}',
      label,
      value: contextLabel || t('memory.correction.history.scopeNameUnavailable', {
        defaultValue: '名称暂不可用',
      }),
    })];
  });
  if (entries.length === 0) return null;
  return entries.join(t('memory.correction.history.scopeSeparator', {
    defaultValue: ', ',
  }));
};

const scopeDimensionLabel = (
  dimension: string,
  t: AppTranslation
): string => {
  const defaults: Record<string, string> = {
    project: '项目',
    activity: '活动',
    place: '地点',
    person: '人物',
    time: '时间',
    custom: '情境',
  };
  return t(`memory.correction.scopes.${dimension}`, {
    defaultValue: defaults[dimension]
      ?? t('memory.correction.scopes.other', {
        defaultValue: '情境',
      }),
  });
};

export const formatCorrectionEntityType = (
  value: string,
  t: AppTranslation
): string => {
  const normalized = String(value || '').trim().toLowerCase();
  return t(`memory.l2.relations.entityTypes.${normalized}`, {
    defaultValue: t('memory.l2.relations.entityTypes.other', {
      defaultValue: 'Other',
    }),
  });
};
