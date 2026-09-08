import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const { browse, createDirectory, reset } = vi.hoisted(() => ({ browse: vi.fn(), createDirectory: vi.fn(), reset: { callback: () => {} } }));
vi.mock('@/api/modules/centerFiles', () => ({ centerFilesApi: { browse, createDirectory } }));
vi.mock('@/runtime/config', () => ({ subscribeRuntimeReset: (callback: () => void) => { reset.callback = callback; } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
import { CenterPathPickerHost } from '@/components/files/CenterPathPickerHost';
import { requestCenterPath, useCenterPathPickerStore } from '@/stores/center-path-picker';
const directory = (path: string) => ({ path, parent: '/', entries: [], next_after: null, selected_file: null });
beforeEach(() => { vi.clearAllMocks(); reset.callback(); browse.mockResolvedValue(directory('/center/home')); });

describe('center filesystem selection', () => {
  it('returns the center path and blocks unvisited text', async () => {
    const result = requestCenterPath('directory'); render(<CenterPathPickerHost />);
    const select = await screen.findByText('centerFiles.select');
    await waitFor(() => expect(select).toBeEnabled());
    fireEvent.change(screen.getByLabelText('centerFiles.path'), { target: { value: '/client/wrong' } });
    expect(select).toBeDisabled();
    fireEvent.change(screen.getByLabelText('centerFiles.path'), { target: { value: '/center/home' } });
    fireEvent.click(select); expect(await result).toBe('/center/home');
  });
  it('selects an existing file after the center resolves its parent', async () => {
    browse.mockResolvedValue({ ...directory('/center'), selected_file: '/center/model.bin', entries: [{ name: 'model.bin', path: '/center/model.bin', kind: 'file' }] });
    const result = requestCenterPath('file', '/center/model.bin'); render(<CenterPathPickerHost />);
    await waitFor(() => expect(screen.getByText('centerFiles.select')).toBeEnabled());
    expect(browse).toHaveBeenCalledWith(expect.objectContaining({ path: '/center/model.bin', resolveFile: true }));
    fireEvent.click(screen.getByText('centerFiles.select')); expect(await result).toBe('/center/model.bin');
  });
  it('cancels the old selection on a center reset and ignores its late response', async () => {
    let resolve!: (value: ReturnType<typeof directory>) => void;
    browse.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const result = requestCenterPath('directory'); render(<CenterPathPickerHost />);
    act(() => reset.callback()); expect(await result).toBeUndefined();
    await act(async () => resolve(directory('/old-center')));
    expect(useCenterPathPickerStore.getState().request).toBeNull(); expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('creates folders on the center and never submits after a failed navigation', async () => {
    createDirectory.mockResolvedValue(directory('/center/home/New'));
    const result = requestCenterPath('directory'); render(<CenterPathPickerHost />);
    await waitFor(() => expect(screen.getByText('centerFiles.select')).toBeEnabled());
    fireEvent.change(screen.getByLabelText('centerFiles.newFolder'), { target: { value: 'New' } });
    fireEvent.click(screen.getByText('centerFiles.create'));
    await waitFor(() => expect(screen.getByLabelText('centerFiles.path')).toHaveValue('/center/home/New'));
    expect(createDirectory).toHaveBeenCalledWith('/center/home', 'New');
    browse.mockRejectedValueOnce(new Error('Permission denied')); fireEvent.click(screen.getByLabelText('centerFiles.home'));
    await screen.findByRole('alert'); expect(screen.getByText('centerFiles.select')).toBeDisabled();
    fireEvent.click(screen.getByText('common.cancel')); expect(await result).toBeUndefined();
  });
});
