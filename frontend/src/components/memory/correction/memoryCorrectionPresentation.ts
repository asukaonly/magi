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
  scope: Record<string, unknown> | null | undefined,
  t: AppTranslation
): string | null => {
  if (!scope) return null;
  const labels: Record<string, string> = {
    project: t('memory.correction.scopes.project', { defaultValue: '项目' }),
    activity: t('memory.correction.scopes.activity', { defaultValue: '活动' }),
    place: t('memory.correction.scopes.place', { defaultValue: '地点' }),
    person: t('memory.correction.scopes.person', { defaultValue: '人物' }),
  };
  const entries = Object.entries(scope)
    .filter(([key, value]) => key in labels && String(value ?? '').trim())
    .map(([key, value]) => t('memory.correction.history.scopeEntry', {
      defaultValue: '{{label}}: {{value}}',
      label: labels[key],
      value: String(value).trim(),
    }));
  if (entries.length === 0) return null;
  return entries.join(t('memory.correction.history.scopeSeparator', {
    defaultValue: ', ',
  }));
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
