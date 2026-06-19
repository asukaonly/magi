import type {
  PortraitObservation,
  PortraitSelfView,
  PortraitSelfViewItem,
  PortraitSelfViewWorldGroupId,
} from '@/api/modules/memoryPortrait';

export type PortraitWorldGroupId = PortraitSelfViewWorldGroupId;

export interface PortraitDisplayItem {
  id: string;
  text: string;
  source: string;
  sourceKey: string | null;
  observation: PortraitObservation;
  assertionId: string | null;
}

export interface PortraitWorldGroup {
  id: PortraitWorldGroupId;
  items: PortraitDisplayItem[];
}

export interface PortraitViewModel {
  worldGroups: PortraitWorldGroup[];
  reviewItems: PortraitDisplayItem[];
  recentItems: PortraitDisplayItem[];
  totalUnderstandingCount: number;
}

const ASSERTION_REF_PATTERN = /^[0-9a-f-]{20,}$/i;

const WORLD_GROUP_IDS: PortraitWorldGroupId[] = ['identity', 'preferences', 'routine', 'communication'];

const STATE_FAMILIES = new Set([
  'state_profile',
  'mood',
  'stress',
  'engagement',
  'trigger',
  'relationship_shift',
  'group_atmosphere',
]);

const FAMILY_GROUPS = new Map<string, PortraitWorldGroupId>([
  ['identity_profile', 'identity'],
  ['preference_profile', 'preferences'],
  ['routine_profile', 'routine'],
  ['communication_profile', 'communication'],
]);

const REVIEW_STATUSES = new Set(['tentative', 'contradicted']);

export const extractAssertionId = (obs: PortraitObservation): string | null => {
  const ref = obs.basis_refs.find((r) => r.startsWith('assertion:') || ASSERTION_REF_PATTERN.test(r));
  if (!ref) return null;
  return ref.startsWith('assertion:') ? ref.slice('assertion:'.length) : ref;
};

const refValue = (obs: PortraitObservation, prefix: string): string | null => {
  const ref = obs.basis_refs.find((r) => r.startsWith(`${prefix}:`));
  return ref ? ref.slice(prefix.length + 1).trim() || null : null;
};

const hasRefPrefix = (obs: PortraitObservation, prefix: string): boolean =>
  obs.basis_refs.some((ref) => ref.startsWith(prefix));

const simplifyText = (text: string): string => {
  const trimmed = text.trim();
  const eqIndex = trimmed.lastIndexOf(' = ');
  if (eqIndex >= 0) {
    return trimmed.slice(eqIndex + 3).trim();
  }
  const colonIndex = trimmed.indexOf(': ');
  if (colonIndex >= 0) {
    return trimmed.slice(colonIndex + 2).trim();
  }
  return trimmed
    .replace(/^偏好：/, '')
    .replace(/^沟通风格：/, '')
    .replace(/^近期状态：/, '')
    .replace(/^常用工具：/, '')
    .trim();
};

const normalizeSourceKey = (value: string): string =>
  value.trim().toLowerCase().replace(/[\s-]+/g, '_');

const sourceLabel = (obs: PortraitObservation): { label: string; key: string | null } => {
  const source = refValue(obs, 'source');
  if (source) {
    return { label: source.replace(/[-_]/g, ' '), key: normalizeSourceKey(source) };
  }
  if (obs.basis_summary && !/l2 assertion/i.test(obs.basis_summary)) {
    if (/l2 tom snapshot/i.test(obs.basis_summary)) {
      return { label: 'tom', key: 'tom' };
    }
    return { label: obs.basis_summary, key: normalizeSourceKey(obs.basis_summary) };
  }
  return { label: '', key: null };
};

const displayItem = (obs: PortraitObservation, index: number): PortraitDisplayItem => {
  const source = sourceLabel(obs);
  return {
    id: `${obs.kind}-${index}-${extractAssertionId(obs) ?? obs.text}`,
    text: simplifyText(obs.text),
    source: source.label,
    sourceKey: source.key,
    observation: obs,
    assertionId: extractAssertionId(obs),
  };
};

const displayItemFromSelfView = (item: PortraitSelfViewItem): PortraitDisplayItem => ({
  id: item.id,
  text: item.text,
  source: item.source,
  sourceKey: item.source_key,
  assertionId: item.assertion_id,
  observation: {
    kind: 'assertion',
    text: item.text,
    basis_count: item.basis_count,
    basis_summary: item.source,
    basis_refs: item.basis_refs,
  },
});

const isReviewItem = (obs: PortraitObservation): boolean => {
  const status = refValue(obs, 'status');
  if (status) {
    return REVIEW_STATUSES.has(status);
  }
  return Boolean(extractAssertionId(obs)) && /l2 assertion/i.test(obs.basis_summary || '');
};

const isRecentItem = (obs: PortraitObservation): boolean => {
  const family = refValue(obs, 'family');
  if (family && STATE_FAMILIES.has(family)) {
    return true;
  }
  return obs.kind === 'reflection' || hasRefPrefix(obs, 'state:');
};

const worldGroupFor = (obs: PortraitObservation): PortraitWorldGroupId | null => {
  const family = refValue(obs, 'family');
  return family ? FAMILY_GROUPS.get(family) ?? null : null;
};

const emptyWorldGroups = (): PortraitWorldGroup[] =>
  WORLD_GROUP_IDS.map((id) => ({ id, items: [] }));

export const buildPortraitViewModel = (observations: PortraitObservation[]): PortraitViewModel => {
  const groups = emptyWorldGroups();
  const groupById = new Map(groups.map((group) => [group.id, group]));
  const reviewItems: PortraitDisplayItem[] = [];
  const recentItems: PortraitDisplayItem[] = [];

  observations.forEach((obs, index) => {
    const item = displayItem(obs, index);
    if (isReviewItem(obs)) {
      reviewItems.push(item);
      return;
    }
    if (isRecentItem(obs)) {
      recentItems.push(item);
      return;
    }
    const groupId = worldGroupFor(obs);
    if (groupId) {
      groupById.get(groupId)?.items.push(item);
    }
  });

  return {
    worldGroups: groups,
    reviewItems,
    recentItems,
    totalUnderstandingCount: observations.length,
  };
};

export const buildPortraitViewModelFromSelfView = (selfView: PortraitSelfView): PortraitViewModel => {
  const groupsById = new Map(selfView.world.groups.map((group) => [group.id, group]));
  return {
    worldGroups: WORLD_GROUP_IDS.map((id) => ({
      id,
      items: (groupsById.get(id)?.items ?? []).map(displayItemFromSelfView),
    })),
    reviewItems: selfView.review.items.map(displayItemFromSelfView),
    recentItems: selfView.recent.items.map(displayItemFromSelfView),
    totalUnderstandingCount: selfView.world.total_count,
  };
};
