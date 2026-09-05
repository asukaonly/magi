import { useState } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import i18n from '@/i18n';
import { Dialog, DialogTrigger, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { SelectField } from '@/components/config-forms/fields';
import { DynamicConfigField } from '@/components/config-forms/DynamicConfigField';
import { ScheduleRunButton } from '@/pages/tasks-pages/components/ScheduleRunButton';
import { L4Tab } from '@/components/memory/L4Tab';
import type { ScheduleDTO } from '@/api/modules/schedules';

const schedule: ScheduleDTO = { schedule_id: 'test', target_type: 'timeline_diary_narrative', target_key: 'test', target_payload: {}, metadata: {}, enabled: true, trigger: { trigger_type: 'interval', config: {} } };
afterEach(async () => { await act(async () => { await i18n.changeLanguage('en'); }); });

it('keeps actual language resources, storage and document metadata in sync', async () => {
  await act(async () => { await i18n.changeLanguage('zh-CN'); });
  expect(localStorage.getItem('magi_language')).toBe('zh');
  expect(document.documentElement.lang).toBe('zh-CN');
  await act(async () => { await i18n.changeLanguage('en'); });
  expect(localStorage.getItem('magi_language')).toBe('en');
  expect(document.documentElement.lang).toBe('en');
});

it('opens and dismisses a translated dialog with the keyboard and restores focus', async () => {
  await i18n.changeLanguage('zh-CN');
  const user = userEvent.setup();
  render(<Dialog><DialogTrigger>打开</DialogTrigger><DialogContent><DialogTitle>标题</DialogTitle><DialogDescription>说明</DialogDescription><button>操作</button></DialogContent></Dialog>);
  await user.tab(); await user.keyboard('{Enter}');
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '关闭' })).toBeInTheDocument();
  await user.keyboard('{Escape}');
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('button', { name: '打开' })).toHaveFocus();
});

describe('selection keyboard controls', () => {
  it('skips disabled choices and returns focus after selection or Escape', async () => {
    const user = userEvent.setup(); const onChange = vi.fn();
    render(<SelectField ariaLabel="Tool" value="first" onChange={onChange} allowEmpty={false} options={[{ value:'first', label:'First' }, { value:'disabled', label:'Unavailable', disabled:true }, { value:'last', label:'Last' }]} />);
    await user.tab(); await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('button', { name:'First' })).toHaveFocus();
    await user.keyboard('{ArrowDown}'); expect(screen.getByRole('button', { name:'Last' })).toHaveFocus();
    await user.keyboard('{Enter}'); expect(onChange).toHaveBeenCalledWith('last');
    expect(screen.getByRole('button', { name:'Tool' })).toHaveFocus();
    await user.keyboard('{ArrowDown}{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name:'Tool' })).toHaveFocus();
  });
});

it('labels array controls and lets Enter add a tag', async () => {
  await i18n.changeLanguage('en'); const user = userEvent.setup();
  function Editor() { const [value,setValue]=useState<unknown>(['initial']); return <DynamicConfigField spec={{ path:'tags', type:'array', description:'Allowed paths', sensitive:false, read_only:false, required:false, is_template:false }} value={value} onChange={setValue} />; }
  render(<Editor />);
  await user.type(screen.getByRole('textbox', { name:'Allowed paths' }), 'second{Enter}');
  expect(screen.getByRole('button', { name:'Remove second' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name:'Add to Allowed paths' })).toBeInTheDocument();
});

it('explains invalid schedule parameters and returns focus from the nested dialog', async () => {
  await i18n.changeLanguage('zh-CN'); const user = userEvent.setup(); const onRun=vi.fn();
  render(<ScheduleRunButton schedule={schedule} onRun={onRun} />);
  const trigger=screen.getByRole('button', { name:i18n.t('tasks.scheduled.actions.runNow') });
  await user.click(trigger); await user.click(screen.getByRole('button', { name:'带参数运行…' }));
  const input=screen.getByRole('textbox', { name:'运行参数（JSON 对象）' });
  await user.type(input, '[[]'); await user.click(screen.getByRole('button', { name:'带参数运行' }));
  expect(screen.getByRole('alert')).toHaveTextContent('运行参数必须是 JSON 对象。'); expect(onRun).not.toHaveBeenCalled();
  await user.keyboard('{Escape}'); await waitFor(() => expect(trigger).toHaveFocus());
});

it('translates procedural memory labels and states', async () => {
  await i18n.changeLanguage('zh-CN');
  render(<L4Tab stats={{ skill_count:1, open_circuit_breakers:0 }} skills={[{ skill_id:'one', skill_name:'Example', skill_category:'task', success_rate:0.9, total_attempts:10, proficiency:0.9, success_count:9, failure_count:1, last_used_at:null, circuit_breaker_state:'closed' }]} />);
  expect(screen.getByText('成功率：90.0%')).toBeInTheDocument();
  expect(screen.getByText('尝试次数：10')).toBeInTheDocument();
  expect(screen.getByText('可用')).toBeInTheDocument();
});
