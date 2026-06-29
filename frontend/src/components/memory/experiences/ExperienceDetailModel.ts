import type {
  L2EpisodeWithSummary,
  L2EpisodeEventPreview,
  L2ExperienceReviewDetail,
  L2ExperienceWithReview,
} from '@/api/modules/memory';
import { resolveTimelineAssetUrl } from '@/utils/timelineAssetUrl';
import { formatExperienceTag } from './ExperienceRow';

export type ExperienceReviewLike = L2ExperienceWithReview | L2ExperienceReviewDetail;

const MACHINE_TITLE_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|^[0-9a-f]{16,}$|^[0-9A-HJKMNP-TV-Z]{12,}$/i;
const MECHANICAL_RECAP_PATTERNS = [
  /Chrome\s*(浏览|browsed)/i,
  /Google Search/i,
  /(访问|visited)\s*\d+\s*(次|times)/i,
  /;\s*Chrome/i,
];

export const normalizeList = (items: string[] | null | undefined): string[] => (
  Array.isArray(items)
    ? items.map(formatExperienceTag).filter((item) => Boolean(item && item.trim()))
    : []
);

const getEpisodeDescription = (episode: L2EpisodeWithSummary): string => (
  String(
    episode.user_note ||
    episode.display_description ||
    episode.episode_summary?.content ||
    episode.summary ||
    episode.slice_narrative ||
    ''
  ).trim()
);

const truncateText = (value: string, maxLength: number): string => {
  const text = value.trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength - 1).trim()}…`;
};

const firstReadableSentence = (value: string): string => {
  const text = value.trim();
  if (!text) {
    return '';
  }
  const [sentence = text] = text.split(/(?<=[。！？.!?])\s+|[；;]\s*/);
  return truncateText(sentence.trim() || text, 150);
};

const isMechanicalRecap = (value: string): boolean => {
  const text = value.trim();
  if (!text) {
    return false;
  }
  const separatorCount = (text.match(/[；;]/g) || []).length;
  const patternHits = MECHANICAL_RECAP_PATTERNS.filter((pattern) => pattern.test(text)).length;
  return separatorCount >= 2 || patternHits >= 2;
};

export const getReadableRecap = (
  experience: ExperienceReviewLike,
  rawDescription: string,
  title: string,
  tags: string[],
  locale: string
): string => {
  if (!rawDescription.trim()) {
    return '';
  }
  if (experience.user_note) {
    return firstReadableSentence(rawDescription);
  }
  if (!isMechanicalRecap(rawDescription) && rawDescription.trim().length <= 180) {
    return firstReadableSentence(rawDescription);
  }
  const subject = title || tags[0] || '';
  if (!subject) {
    return locale.startsWith('zh')
      ? '这段经历已经整理成一段可以回看的记录。'
      : 'This experience has been shaped into something you can revisit.';
  }
  return locale.startsWith('zh')
    ? `这段经历主要围绕「${subject}」展开。`
    : `This experience centers on ${subject}.`;
};

export const getEpisodeEvents = (
  episode: L2EpisodeWithSummary,
  eventsByEpisode: Map<string, L2EpisodeEventPreview[]>
): L2EpisodeEventPreview[] => eventsByEpisode.get(episode.episode_id) ?? [];

const getEventPreviewText = (event: L2EpisodeEventPreview): string => (
  String(event.content_preview || '').trim()
);

const getSourceEpisodeFallbackFromEvents = (
  episode: L2EpisodeWithSummary,
  eventsByEpisode: Map<string, L2EpisodeEventPreview[]>
): string => {
  const event = getEpisodeEvents(episode, eventsByEpisode).find((item) => getEventPreviewText(item));
  return event ? firstReadableSentence(getEventPreviewText(event)) : '';
};

export const getReadableSourceEpisodeTitle = (
  episode: L2EpisodeWithSummary,
  index: number,
  fallbackTemplate: string,
  eventsByEpisode: Map<string, L2EpisodeEventPreview[]>
): string => {
  const values = [
    episode.user_label,
    episode.display_title,
    episode.episode_summary?.label,
    episode.label,
    episode.summary,
    episode.slice_narrative,
  ];
  const title = values.find((value) => typeof value === 'string' && value.trim())?.trim() ?? '';
  if (!title || MACHINE_TITLE_PATTERN.test(title)) {
    return getSourceEpisodeFallbackFromEvents(episode, eventsByEpisode)
      || fallbackTemplate.replace('{{index}}', String(index + 1));
  }
  return title;
};

export const getReadableSourceEpisodeSummary = (
  episode: L2EpisodeWithSummary,
  eventsByEpisode: Map<string, L2EpisodeEventPreview[]>
): string => {
  const summary = getEpisodeDescription(episode);
  if (summary) {
    return summary;
  }
  return getEpisodeEvents(episode, eventsByEpisode)
    .map(getEventPreviewText)
    .filter(Boolean)
    .slice(0, 2)
    .map((item) => firstReadableSentence(item))
    .join(' / ');
};

export const getExperienceCoverUrl = (episodes: L2EpisodeWithSummary[]): string | null => {
  for (const episode of episodes) {
    const url = resolveTimelineAssetUrl(episode.representative_asset_ref);
    if (url) {
      return url;
    }
  }
  return null;
};

export const formatSourceLabel = (value: string | null | undefined): string => (
  String(value || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .trim()
);

export const formatEventTime = (value: number | null | undefined, locale: string): string => {
  if (typeof value !== 'number') {
    return '';
  }
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value * 1000));
};
