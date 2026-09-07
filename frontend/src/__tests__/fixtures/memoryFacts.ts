import type { L2Assertion } from '@/api/modules/memory';

export const strawberryAssertion: L2Assertion = {
  assertion_id: 'assert_f0246f5594db404196b430b6bc9a5ab4',
  entity_id: 'user:local_user', entity_type: 'user', entity_name: '用户',
  trait_family: 'preference', trait_name: 'preference.affinity', trait_value: 'like',
  target_entity_id: 'entity_strawberry', target_entity_type: 'food', target_entity_name: '草莓',
  natural_summary: '用户喜欢草莓。', display_text: '用户喜欢草莓。', value_options: ['like', 'dislike'],
  confidence_score: 0.8, evidence_events: ['01M1Y2R15963D9PKMZ1FGE7FW4'],
  validation_state: 'tentative', status: 'tentative', volatility_index: 0.1,
  source_domain: 'user_authored', inference_depth: 'direct',
  first_inferred_at: 1788789655, last_validated_at: 1788789655, updated_at: 1788789655,
  user_feedback: null, user_feedback_at: null,
};

export const memoryFactCases: Array<{ name: string; assertion: L2Assertion; expected: string }> = [
  { name: 'like', assertion: strawberryAssertion, expected: '用户喜欢草莓。' },
  { name: 'dislike', assertion: { ...strawberryAssertion, assertion_id: 'assert-dislike', trait_value: 'dislike', natural_summary: '用户不喜欢榴莲。', display_text: '用户不喜欢榴莲。', target_entity_id: 'durian', target_entity_name: '榴莲' }, expected: '用户不喜欢榴莲。' },
  { name: 'interest', assertion: { ...strawberryAssertion, assertion_id: 'assert-interest', trait_family: 'interest', trait_name: 'interest.attention', trait_value: 'interested', target_entity_name: '天文学', natural_summary: '用户对天文学感兴趣。', display_text: '用户对天文学感兴趣。', value_options: ['interested'] }, expected: '用户对天文学感兴趣。' },
  { name: 'address', assertion: { ...strawberryAssertion, assertion_id: 'assert-address', trait_family: 'communication', trait_name: 'communication.address.preferred', trait_value: '明日香', target_entity_id: null, target_entity_name: null, natural_summary: '用户希望被称呼为明日香。', display_text: '用户希望被称呼为明日香。', value_options: null }, expected: '用户希望被称呼为明日香。' },
  { name: 'recent', assertion: { ...strawberryAssertion, assertion_id: 'assert-recent', temporal_scope: 'recent', natural_summary: '用户最近喜欢草莓。', display_text: '用户最近喜欢草莓。' }, expected: '用户最近喜欢草莓。' },
  { name: 'second object', assertion: { ...strawberryAssertion, assertion_id: 'assert-blueberry', target_entity_id: 'blueberry', target_entity_name: '蓝莓', natural_summary: '用户喜欢蓝莓。', display_text: '用户喜欢蓝莓。' }, expected: '用户喜欢蓝莓。' },
  { name: 'missing summary', assertion: { ...strawberryAssertion, assertion_id: 'assert-no-summary', natural_summary: null, display_text: '用户喜欢草莓。' }, expected: '用户喜欢草莓。' },
  { name: 'unresolved target', assertion: { ...strawberryAssertion, assertion_id: 'assert-unresolved', target_entity_id: 'ent_private_missing', target_entity_name: null, natural_summary: null, display_text: '用户喜欢尚未解析的对象。' }, expected: '用户喜欢尚未解析的对象。' },
  { name: 'other subject', assertion: { ...strawberryAssertion, assertion_id: 'assert-other-person', entity_id: 'person_limei', entity_type: 'person', entity_name: '李梅', natural_summary: '李梅喜欢草莓。', display_text: '李梅喜欢草莓。' }, expected: '李梅喜欢草莓。' },
];
