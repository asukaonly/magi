import type {
  SelfPortraitObservation,
  PortraitSelfView,
  PortraitSelfViewItem,
  PortraitSelfViewWorldGroupId,
} from '@/api/modules/memoryPortraitSelf';

export type PortraitWorldGroupId = PortraitSelfViewWorldGroupId;

export interface PortraitDisplayItem {
  id: string;
  text: string;
  source: string;
  sourceKey: string | null;
  observation: SelfPortraitObservation;
  assertionId: string | null;
  claimKind?: string | null;
}

export interface PortraitWorldGroup {
  id: PortraitWorldGroupId;
  summary: string;
  items: PortraitDisplayItem[];
}

export interface PortraitViewModel {
  worldGroups: PortraitWorldGroup[];
  reviewItems: PortraitDisplayItem[];
  recentItems: PortraitDisplayItem[];
  totalUnderstandingCount: number;
}

const ASSERTION_REF_PATTERN = /^[0-9a-f-]{20,}$/i;

const WORLD_GROUP_IDS: PortraitWorldGroupId[] = [
  'identity',
  'projects',
  'preferences',
  'work_style',
];

const STATE_FAMILIES = new Set([
  'state_profile',
  'mood',
  'stress',
  'engagement',
  'trigger',
  'relationship_shift',
  'group_atmosphere',
]);

const REVIEW_STATUSES = new Set(['tentative', 'contradicted']);
const INTERNAL_SOURCE_KEYS = new Set(['external_activity']);

const normalizeUserFacingSource = (
  source: string,
  sourceKey: string | null | undefined
): { label: string; key: string | null } => {
  const key = sourceKey || (source ? normalizeSourceKey(source) : null);
  if (key && INTERNAL_SOURCE_KEYS.has(key)) {
    return { label: '', key: null };
  }
  return { label: source, key: key ?? null };
};

export const extractAssertionId = (obs: SelfPortraitObservation): string | null => {
  const ref = obs.basis_refs.find((r) => r.startsWith('assertion:') || ASSERTION_REF_PATTERN.test(r));
  if (!ref) return null;
  return ref.startsWith('assertion:') ? ref.slice('assertion:'.length) : ref;
};

const refValue = (obs: SelfPortraitObservation, prefix: string): string | null => {
  const ref = obs.basis_refs.find((r) => r.startsWith(`${prefix}:`));
  return ref ? ref.slice(prefix.length + 1).trim() || null : null;
};

const hasRefPrefix = (obs: SelfPortraitObservation, prefix: string): boolean =>
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

const sourceLabel = (obs: SelfPortraitObservation): { label: string; key: string | null } => {
  const source = refValue(obs, 'source');
  if (source) {
    return normalizeUserFacingSource(source.replace(/[-_]/g, ' '), normalizeSourceKey(source));
  }
  if (obs.basis_summary && !/l2 assertion/i.test(obs.basis_summary)) {
    if (/l2 tom snapshot/i.test(obs.basis_summary)) {
      return { label: 'tom', key: 'tom' };
    }
    return { label: obs.basis_summary, key: normalizeSourceKey(obs.basis_summary) };
  }
  return { label: '', key: null };
};

const displayItem = (obs: SelfPortraitObservation, index: number): PortraitDisplayItem => {
  const source = sourceLabel(obs);
  return {
    id: `${obs.kind}-${index}-${extractAssertionId(obs) ?? obs.text}`,
    text: simplifyText(obs.text),
    source: source.label,
    sourceKey: source.key,
    observation: obs,
    assertionId: extractAssertionId(obs),
    claimKind: refValue(obs, 'claim_kind'),
  };
};

const displayItemFromSelfView = (item: PortraitSelfViewItem): PortraitDisplayItem => {
  const source = normalizeUserFacingSource(item.source, item.source_key);
  return {
    id: item.id,
    text: item.text,
    source: source.label,
    sourceKey: source.key,
    assertionId: item.assertion_id,
    claimKind: item.claim_kind ?? null,
    observation: {
      kind: 'assertion',
      text: item.text,
      basis_count: item.basis_count,
      basis_summary: source.label,
      basis_refs: item.basis_refs,
    },
  };
};

const isReviewItem = (obs: SelfPortraitObservation): boolean => {
  const status = refValue(obs, 'status');
  if (status) {
    return REVIEW_STATUSES.has(status);
  }
  return Boolean(extractAssertionId(obs)) && /l2 assertion/i.test(obs.basis_summary || '');
};

const isRecentItem = (obs: SelfPortraitObservation): boolean => {
  const family = refValue(obs, 'family');
  if (family && STATE_FAMILIES.has(family)) {
    return true;
  }
  return obs.kind === 'reflection' || hasRefPrefix(obs, 'state:');
};

const worldGroupFor = (obs: SelfPortraitObservation): PortraitWorldGroupId | null => {
  const explicitGroup = refValue(obs, 'world_group');
  if (explicitGroup && WORLD_GROUP_IDS.includes(explicitGroup as PortraitWorldGroupId)) {
    return explicitGroup as PortraitWorldGroupId;
  }
  const claimKind = refValue(obs, 'claim_kind');
  switch (claimKind) {
    case 'identity_fact':
      return 'identity';
    case 'active_work':
      return 'projects';
    case 'preference_interest':
      return 'preferences';
    case 'collaboration_style':
      return 'work_style';
    default:
      return null;
  }
};

const emptyWorldGroups = (): PortraitWorldGroup[] =>
  WORLD_GROUP_IDS.map((id) => ({ id, summary: '', items: [] }));

export const buildPortraitViewModel = (observations: SelfPortraitObservation[]): PortraitViewModel => {
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
      summary: groupsById.get(id)?.summary ?? '',
      items: (groupsById.get(id)?.items ?? []).map(displayItemFromSelfView),
    })),
    reviewItems: selfView.review.items.map(displayItemFromSelfView),
    recentItems: selfView.recent.items.map(displayItemFromSelfView),
    totalUnderstandingCount: selfView.world.total_count,
  };
};
