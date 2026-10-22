import type { PersonalItem, PersonalItemDetail } from '@/api/modules/personalTasks';

export const personalItem = (overrides: Partial<PersonalItem> = {}): PersonalItem => ({
  id: 'item-one', user_id: 'local_user', title: 'Prepare quote', body_md: 'Budget 40,000. Local deployment required.',
  kind: 'action', parent_id: null, status: 'active', origin: 'user',
  defer_until: null, due: '2030-01-05', remind_at: null, timezone: 'Asia/Shanghai', references: [],
  version: 1, created_at: 100, updated_at: 100, closed_at: null,
  reminder_revision: 1, reminder_synced_revision: 1, reminder_delivered_revision: 0,
  ...overrides,
});

export const personalDetail = (item = personalItem()): PersonalItemDetail => ({item, children: [], changes: [], next_history_offset: null});
