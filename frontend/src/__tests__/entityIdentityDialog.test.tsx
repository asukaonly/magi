import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EntityIdentityDialog } from '@/components/memory/identity/EntityIdentityDialog';
import { entityIdentityApi, parseIdentityPreview, type EntityChangeCommand } from '@/api/modules/entityIdentity';
import { memoryApi } from '@/api/modules/memory';
import examples from '../../../contracts/api/frontend-identity-examples.json';

vi.mock('react-i18next', async () => {
  const { default: zh } = await import('@/i18n/locales/zh-CN/app.json');
  return { useTranslation: () => ({ t: (key: string, opts?: Record<string, unknown>) => {
    const value = key.split('.').reduce<unknown>((v, part) => v && typeof v === 'object' ? Reflect.get(v, part) : undefined, zh);
    return String(value ?? opts?.defaultValue ?? key).replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name] ?? ''));
  } }) };
});
vi.mock('sonner', () => ({ toast: { success: vi.fn(), warning: vi.fn() } }));
vi.mock('@/api/modules/memory', () => ({ memoryApi: { getL2Entities: vi.fn(), getL1Events: vi.fn() } }));

const entity = examples.preview.entity;
const command: EntityChangeCommand = { ...examples.preview.command, kind: 'type_correction' };
const preview = parseIdentityPreview(examples.preview, command);

beforeEach(() => {
  vi.restoreAllMocks();
  vi.mocked(memoryApi.getL2Entities).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  vi.mocked(memoryApi.getL1Events).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
});

describe('entity identity decision UI', () => {
  it('previews a classification before applying and retries the same uncertain operation', async () => {
    const inspect = vi.spyOn(entityIdentityApi, 'preview').mockResolvedValue(preview);
    const apply = vi.spyOn(entityIdentityApi, 'apply').mockRejectedValueOnce(new Error('Network error')).mockResolvedValue({ ...examples.result, kind: 'type_correction', derivation_state: 'pending' });
    const onSaved = vi.fn();
    const onClose = vi.fn();
    render(<EntityIdentityDialog entity={entity} onSaved={onSaved} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText('正确的实体类别'), { target: { value: 'food' } });
    await userEvent.click(screen.getByRole('button', { name: '查看影响' }));
    expect(await screen.findByText('将“苹果”从“其他”改为“食物”。')).toBeInTheDocument();
    expect(inspect).toHaveBeenCalledWith(command);
    expect(apply).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '确认修改' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('尚未收到修改确认');
    await userEvent.click(screen.getByRole('button', { name: '确认修改' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(apply.mock.calls[0]).toEqual(apply.mock.calls[1]);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('allows searching across types without selecting a homonym automatically', async () => {
    const target = { entity_id: 'entity:company', canonical_name: '苹果公司', entity_type: 'organization', aliases: [] };
    vi.mocked(memoryApi.getL2Entities).mockResolvedValue({ items: [target], total: 1, limit: 50, offset: 0 });
    const inspect = vi.spyOn(entityIdentityApi, 'preview').mockResolvedValue({ ...preview, command: { ...command, kind: 'merge', new_type: null, target_entity_id: target.entity_id }, target });
    render(<EntityIdentityDialog entity={entity} onSaved={vi.fn()} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: '合并为同一对象' }));
    const option = await screen.findByRole('button', { name: '苹果公司 · 组织' });
    expect(screen.getByRole('button', { name: '查看影响' })).toBeDisabled();
    await userEvent.click(option);
    await userEvent.click(screen.getByRole('button', { name: '查看影响' }));
    await waitFor(() => expect(inspect).toHaveBeenCalledWith(expect.objectContaining({ kind: 'merge', target_entity_id: target.entity_id, new_type: null })));
    expect(await screen.findByText('将“苹果 · 其他”合并到“苹果公司 · 组织”，保留后者的名称和类别。')).toBeInTheDocument();
  });

  it('requires another preview after the server rejects stale state', async () => {
    vi.spyOn(entityIdentityApi, 'preview').mockResolvedValue(preview);
    vi.spyOn(entityIdentityApi, 'apply').mockRejectedValue({ isAxiosError: true, response: { status: 409, data: {} } });
    render(<EntityIdentityDialog entity={entity} review={{ review_id: 'review', entity, proposed_type: 'food', evidence_event_ids: [], version: 1 }} onSaved={vi.fn()} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: '查看影响' }));
    await userEvent.click(await screen.findByRole('button', { name: '确认修改' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('旧预览已失效');
    expect(screen.queryByRole('button', { name: '确认修改' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '查看影响' })).toBeEnabled();
  });
});
