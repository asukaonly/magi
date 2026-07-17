import type {
  L2Assertion,
  L2Entity,
  L2Relation,
  L2Snapshot,
} from '@/api/modules/memory';

export type KnowledgeDetailRow = { label: string; value: string | number | null | undefined };
export type KnowledgeStatusGroup = 'active' | 'needsReview' | 'conflicted' | 'deprecated';
export type KnowledgeBaseGroupId = 'all' | 'aboutSelf' | 'preferences' | 'relationships' | 'workProjects' | 'interests' | 'other';
export type MemoryTranslateFn = (key: string, options?: Record<string, unknown>) => string;
export type KnowledgeCorrectionAction = 'replace' | 'remove';

export interface KnowledgeItem {
  id: string;
  kind: 'relation' | 'assertion';
  groupId: KnowledgeBaseGroupId;
  kindLabel: string;
  title: string;
  body?: string | null;
  entityType?: string | null;
  entityIds: string[];
  statusGroup: KnowledgeStatusGroup;
  statusLabel: string;
  confidence?: number | null;
  evidenceCount?: number | null;
  evidenceIds?: string[];
  updatedAt?: number | null;
  expectedUpdatedAt?: number | null;
  detailRows: KnowledgeDetailRow[];
  technicalRows?: KnowledgeDetailRow[];
  searchableText: string;
  assertionId?: string;
  correctionValue?: string;
  userFeedback?: string | null;
}

export interface KnowledgeBaseGroup {
  id: KnowledgeBaseGroupId;
  label: string;
  items: KnowledgeItem[];
  counts: {
    stable: number;
    review: number;
    relations: number;
    deprecated: number;
  };
  totalCount: number;
}

export interface EntityOverviewItem {
  id: string;
  name: string;
  typeLabel: string | null;
  snapshot?: L2Snapshot;
  summary: string[];
  activeItems: KnowledgeItem[];
  reviewItems: KnowledgeItem[];
  relationCount: number;
  assertionCount: number;
  knowledgeCount: number;
  reviewCount: number;
  lastUpdatedAt?: number | null;
  score: number;
  searchableText: string;
}

export interface BuildKnowledgeItemsParams {
  relations: L2Relation[];
  assertions: L2Assertion[];
  entityById: Map<string, L2Entity>;
  selfEntityAliases: Set<string>;
  t: MemoryTranslateFn;
}

export interface FilterKnowledgeItemsParams {
  query: string;
  statusFilter: string;
  entityTypeFilter: string;
}

export interface BuildEntityOverviewItemsParams {
  entities: L2Entity[];
  entityById: Map<string, L2Entity>;
  snapshots: L2Snapshot[];
  knowledgeItems: KnowledgeItem[];
  selfEntityAliases: Set<string>;
  t: MemoryTranslateFn;
}

export const ENTITY_KNOWLEDGE_PREVIEW_LIMIT = 20;
