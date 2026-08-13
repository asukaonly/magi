type MemoryTranslateFn = (key: string) => string;

export const KNOWN_MEMORY_EVENT_SOURCES = [
  'chat_projector',
  'runtime_action_emitter',
  'timeline_importer',
  'manual_journal',
  'history_import',
  'l2_lab',
  'chat',
  'chrome_history',
  'photo_library',
  'screen_time',
  'terminal_history',
  'git_activity',
] as const;

const HISTORY_IMPORT_MEMORY_SOURCE = 'history_import';

export const isHistoryImportMemorySource = (
  source: string | null | undefined,
): boolean => String(source || '').trim().toLowerCase() === HISTORY_IMPORT_MEMORY_SOURCE;

const resolveTranslation = (
  t: MemoryTranslateFn,
  key: string
): string | null => {
  const translated = t(key);
  return translated !== key ? translated : null;
};

export const getMemorySourceLabel = (
  t: MemoryTranslateFn,
  source: string
): string =>
  resolveTranslation(t, `memory.sources.${source}`)
  || resolveTranslation(t, `timeline.sources.${source}`)
  || source;

export const buildMemorySourceOptions = (
  t: MemoryTranslateFn,
  observedSources: string[]
): Array<{ value: string; label: string }> => {
  const knownSources = [...KNOWN_MEMORY_EVENT_SOURCES];
  const extraSources = observedSources
    .filter((source) => source && !knownSources.includes(source as (typeof KNOWN_MEMORY_EVENT_SOURCES)[number]))
    .sort((left, right) => left.localeCompare(right));

  return [...knownSources, ...extraSources].map((source) => ({
    value: source,
    label: getMemorySourceLabel(t, source),
  }));
};
