import type {
  PortraitSelfView,
  PortraitSelfViewItem,
  PortraitSelfViewWorldGroupId,
} from '@/api/modules/memoryPortraitSelf';

export type PortraitWorldGroupId = PortraitSelfViewWorldGroupId;

export interface PortraitDisplayItem {
  id: string;
  text: string;
  correctionValue?: string | null;
  source: string;
  sourceKey: string | null;
  assertionId: string | null;
  updatedAt?: number | null;
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

const WORLD_GROUP_IDS: PortraitWorldGroupId[] = [
  'identity',
  'projects',
  'preferences',
  'work_style',
];

const INTERNAL_SOURCE_KEYS = new Set(['external_activity']);

const normalizeSourceKey = (value: string): string =>
  value.trim().toLowerCase().replace(/[\s-]+/g, '_');

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

const displayItem = (item: PortraitSelfViewItem): PortraitDisplayItem => {
  const source = normalizeUserFacingSource(item.source, item.source_key);
  return {
    id: item.id,
    text: item.text,
    correctionValue: item.correction_value ?? null,
    source: source.label,
    sourceKey: source.key,
    assertionId: item.assertion_id,
    updatedAt: item.updated_at ?? null,
    claimKind: item.claim_kind ?? null,
  };
};

export const buildPortraitViewModel = (selfView: PortraitSelfView): PortraitViewModel => {
  const groupsById = new Map(selfView.world.groups.map((group) => [group.id, group]));
  return {
    worldGroups: WORLD_GROUP_IDS.map((id) => ({
      id,
      summary: groupsById.get(id)?.summary ?? '',
      items: (groupsById.get(id)?.items ?? []).map(displayItem),
    })),
    reviewItems: selfView.review.items.map(displayItem),
    recentItems: selfView.recent.items.map(displayItem),
    totalUnderstandingCount: selfView.world.total_count,
  };
};
