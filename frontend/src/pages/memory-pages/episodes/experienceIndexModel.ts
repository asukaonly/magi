import type {
  L2ExperienceSeed,
  L2ExperienceWithReview,
} from '@/api/modules/memory';
import {
  formatExperienceTag,
  getExperienceEntityLabels,
} from '@/components/memory/experiences/ExperienceRow';

export interface ExperienceMonthGroup {
  key: string;
  label: string;
  items: L2ExperienceWithReview[];
}

const getExperienceReviewTimestamp = (experience: L2ExperienceWithReview): number => Math.max(
  Number(experience.updated_at ?? 0),
  Number(experience.experience_review?.updated_at ?? 0),
  Number(experience.time_end ?? 0),
  Number(experience.time_start ?? 0),
  0
);

export const sortExperiencesForReview = (
  items: L2ExperienceWithReview[]
): L2ExperienceWithReview[] => [...items].sort((a, b) => {
  if (Boolean(a.user_pinned) !== Boolean(b.user_pinned)) {
    return a.user_pinned ? -1 : 1;
  }
  const updatedDiff = getExperienceReviewTimestamp(b) - getExperienceReviewTimestamp(a);
  if (updatedDiff !== 0) {
    return updatedDiff;
  }
  return Number(b.narrative_score ?? 0) - Number(a.narrative_score ?? 0);
});

const normalizeTags = (items: string[] | null | undefined): string[] => (
  Array.isArray(items)
    ? items.map(formatExperienceTag).filter((item) => Boolean(item && item.trim()))
    : []
);

const uniqueItems = (items: string[]): string[] => Array.from(new Set(items.filter(Boolean)));

export const getExperienceTags = (experience: L2ExperienceWithReview, limit = 8): string[] => uniqueItems([
  ...getExperienceEntityLabels(experience),
  ...normalizeTags(experience.primary_topic_keys),
  ...normalizeTags(experience.primary_place_ids),
]).slice(0, limit);

const getExperienceTime = (experience: L2ExperienceWithReview): number => (
  Number(experience.time_start ?? experience.time_end ?? experience.updated_at ?? 0)
);

const getMonthKey = (experience: L2ExperienceWithReview): string => {
  const time = getExperienceTime(experience);
  if (!time) {
    return 'unknown';
  }
  const date = new Date(time * 1000);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
};

const getMonthLabel = (key: string, locale: string, unknownLabel: string): string => {
  if (key === 'unknown') {
    return unknownLabel;
  }
  const [year, month] = key.split('-').map((value) => Number(value));
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'long',
  }).format(new Date(year, month - 1, 1));
};

export const groupExperiencesByMonth = (
  items: L2ExperienceWithReview[],
  locale: string,
  unknownLabel: string
): ExperienceMonthGroup[] => {
  const groups = new Map<string, L2ExperienceWithReview[]>();
  items.forEach((experience) => {
    const key = getMonthKey(experience);
    groups.set(key, [...(groups.get(key) ?? []), experience]);
  });
  return Array.from(groups.entries()).map(([key, groupItems]) => ({
    key,
    label: getMonthLabel(key, locale, unknownLabel),
    items: groupItems,
  }));
};

export const getSeedTags = (seed: L2ExperienceSeed, limit = 3): string[] => uniqueItems([
  ...(seed.display_tags || []).map(formatExperienceTag),
  ...normalizeTags(seed.anchor_entity_ids),
  ...normalizeTags(seed.anchor_place_ids),
  ...normalizeTags(seed.anchor_topic_keys),
]).slice(0, limit);

export const getSeedTitle = (seed: L2ExperienceSeed, fallback: string): string => (
  String(seed.display_title || seed.title || '').trim() || fallback
);

export const getSeedDescription = (
  seed: L2ExperienceSeed,
  tags: string[],
  fallback: string,
  genericFallback: string
): string => {
  const description = String(seed.display_description || seed.description || '').trim();
  if (description) {
    return description;
  }
  if (tags.length > 0) {
    return fallback.replace('{{tags}}', tags.join('、'));
  }
  return genericFallback;
};
