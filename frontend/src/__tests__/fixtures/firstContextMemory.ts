import type { L1Event } from '@/api/modules/memory';
import type { PortraitSelfViewItem, SelfPortraitPayload } from '@/api/modules/memoryPortraitSelf';
import { DEFAULT_USER_ID } from '@/constants';

export const firstContextItem: PortraitSelfViewItem = {
  id: 'name', text: '用户希望被称呼为明日香。', source: '', source_key: null,
  assertion_id: 'assert-name', evidence_basis: 'direct_report', basis_count: 1,
  basis_refs: ['event:event-name'], display_status: 'complete',
  correction_value: '明日香', correction_trait_name: 'communication.address.preferred', correction_value_options: null,
};
export const firstContextPortrait = (items = [firstContextItem]): SelfPortraitPayload => ({
  generated_at: 1, is_stale: false, is_cold_start: false, cold_start_line: null, cold_start_reason: null,
  self_view: { world: { total_count: items.length, groups: [{ id: 'identity', items }] }, recent: { items: [] }, review: { items: [] } },
});
export const firstContextEvent: L1Event = {
  event_id: 'event-name', event_type: 'USER_MESSAGE', timestamp: 1, source: 'chat',
  source_item_id: 'first-context-name', session_id: 'session-1', user_id: DEFAULT_USER_ID,
  author_type: 'user', content: '明日香', memory_domain: 'user', retention_class: 'permanent',
  importance_score: 0.8, cognition_eligible: true,
};
