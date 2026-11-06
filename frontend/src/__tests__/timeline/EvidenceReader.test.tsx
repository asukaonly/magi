import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import i18n from '@/i18n';
import type {TimelineClusterBlock, TimelineContextBundle} from '@/api/modules/timeline';
vi.mock('@/runtime/desktop', () => ({openExternalUrl:vi.fn().mockResolvedValue(undefined)}));
import {openExternalUrl} from '@/runtime/desktop';
import {EvidenceReader} from '@/components/timeline/immersive/EvidenceReader';
const cluster: TimelineClusterBlock = {block_id:'group', time_start:100, time_end:200,duration_seconds:100,label:'Reading',summary:'',dominant_mode:'activity',source_types:['chrome_history'],event_count:2,representative_event_ids:[],keywords:[],media_refs:[]};
const context = (events: Array<Record<string, unknown>>): TimelineContextBundle => ({anchor:{anchor_id:'group',anchor_type:'cluster',title:'',summary:''},l1_events:events,l2_state_evidence:[],l3_reflections:[],l4_related_procedures:[],chat_excerpts:[],runtime_trace:[]});
beforeEach(async()=>{vi.clearAllMocks();await i18n.changeLanguage('zh-CN');});
describe('readable source evidence',()=>{
  it('merges repeated URLs, keeps the earliest title and displays recorded visits without repeated prose',async()=>{
    const event={source_type:'chrome_history',url:'https://example.com/a',title:'Page',summary:'Page (2 visits)',visit_count:2};
    render(<EvidenceReader cluster={cluster} context={context([{...event,event_id:'later',timestamp:200,title:'Later title'},{...event,event_id:'first',timestamp:100}])} loading={false} failed={false} onClose={vi.fn()} onRetry={vi.fn()}/>);
    expect(screen.getByRole('button',{name:'Page'})).toBeInTheDocument();
    expect(screen.queryByText('Later title')).not.toBeInTheDocument();
    expect(screen.queryByText('Page (2 visits)')).not.toBeInTheDocument();
    expect(screen.getByText('访问 4 次')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button',{name:'Page'}));
    expect(openExternalUrl).toHaveBeenCalledWith('https://example.com/a');
  });
  it('does not make unsafe URLs clickable and preserves authored prompt examples',()=>{
    const prompt='请解释 <environment_context>，这是我贴的代码示例。';
    render(<EvidenceReader cluster={cluster} context={context([{event_id:'a',timestamp:100,title:'Request',source_type:'codex_agent_history',url:'javascript:alert(1)',summary:'',user_prompts:[prompt]}])} loading={false} failed={false} onClose={vi.fn()} onRetry={vi.fn()}/>);
    expect(screen.getByText(prompt)).toBeInTheDocument();
    expect(screen.getByText('你的提问')).toBeInTheDocument();
    expect(screen.queryByRole('button',{name:'Request'})).not.toBeInTheDocument();
  });
  it('offers a retry after a load failure',async()=>{
    const retry=vi.fn();
    render(<EvidenceReader cluster={cluster} context={null} loading={false} failed onClose={vi.fn()} onRetry={retry}/>);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button',{name:'重试'}));
    expect(retry).toHaveBeenCalledOnce();
  });
});
