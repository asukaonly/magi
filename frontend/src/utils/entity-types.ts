import { ENTITY_TYPES } from '@/api/generated/entity-types';

type Translate = (key: string, options?: Record<string, unknown>) => string;
const byKey = new Map<string, (typeof ENTITY_TYPES)[number]>();
for (const descriptor of ENTITY_TYPES) {
  byKey.set(descriptor.key, descriptor);
  for (const alias of descriptor.aliases) byKey.set(alias, descriptor);
}

export const EXTRACTABLE_ENTITY_TYPES = ENTITY_TYPES.filter((item) => !item.structured_only);

export function canChangeEntityIdentity(entity: { entity_id: string; entity_type: string }): boolean {
  const descriptor = byKey.get(entity.entity_type);
  return !entity.entity_id.startsWith('user:') && Boolean(descriptor && !descriptor.structured_only);
}

export function getEntityTypeLabel(value: unknown, t: Translate): string {
  if (value === 'user') return t('memory.governance.relations.entityTypes.user');
  const descriptor = typeof value === 'string' ? byKey.get(value.trim().toLowerCase()) : undefined;
  return descriptor
    ? t(`memory.entityTypes.${descriptor.key}`)
    : t('memory.governance.relations.entityTypes.unknown');
}
