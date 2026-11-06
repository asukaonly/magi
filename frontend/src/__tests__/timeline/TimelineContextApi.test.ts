import { beforeEach, describe, expect, it, vi } from 'vitest';
const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('@/api/client', () => ({api: transport, unwrapGatewayPayload: (value: unknown) => value}));
import {timelineApi} from '@/api/modules/timeline';
const bundle = {
  anchor: {anchor_id:'episode:a/b', anchor_type:'episode', title:'Review', summary:''},
  l1_events:[{event_id:'a',timestamp:12,title:'Codex session',summary:'Request',source_type:'codex_agent_history',user_prompts:['Request']}],
  l2_state_evidence:[],l3_reflections:[],l4_related_procedures:[],chat_excerpts:[],runtime_trace:[],
};
beforeEach(() => vi.resetAllMocks());
describe('timeline detail transport', () => {
  it('encodes anchors and preserves authored prompt content', async () => {
    transport.get.mockResolvedValue(bundle);
    expect(await timelineApi.getContext('episode:a/b')).toEqual(bundle);
    expect(transport.get).toHaveBeenCalledWith('/timeline/context/episode%3Aa%2Fb');
  });
  it('posts all selected members without using preview representatives', async () => {
    transport.post.mockResolvedValue(bundle);
    await timelineApi.getEventContext(['a','b','c','d']);
    expect(transport.post).toHaveBeenCalledWith('/timeline/context',{event_ids:['a','b','c','d']});
  });
  it.each([
    {...bundle, l1_events:[{...bundle.l1_events[0],timestamp:'yesterday'}]},
    {...bundle, l1_events:[{...bundle.l1_events[0],user_prompts:[{}]}]},
    {...bundle, l1_events:null},
    {...bundle, anchor:null},
  ])('rejects malformed detail responses', async value => {
    transport.post.mockResolvedValue(value);
    await expect(timelineApi.getEventContext(['a'])).rejects.toThrow();
  });
});
