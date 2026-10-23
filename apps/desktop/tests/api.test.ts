import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ invoke: vi.fn(), open: vi.fn() }));
vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke }));
vi.mock('@tauri-apps/plugin-dialog', () => ({ open: mocks.open }));
import { desktopApi } from '../src/api';
beforeEach(() => { mocks.invoke.mockReset().mockResolvedValue(undefined); mocks.open.mockReset().mockResolvedValue(null); });
describe('bounded Tauri command adapter', () => {
  it('uses exactly named command arguments', async () => {
    await desktopApi.saveKey(null, 'Fake name', 'FAKE_KEY'); expect(mocks.invoke).toHaveBeenLastCalledWith('save_key', { id: null, name: 'Fake name', secret: 'FAKE_KEY' });
    await desktopApi.preview(['fake-id']); expect(mocks.invoke).toHaveBeenLastCalledWith('preview', { selected: ['fake-id'] });
    await desktopApi.applyPreview('fake-plan', true); expect(mocks.invoke).toHaveBeenLastCalledWith('apply_preview', { id: 'fake-plan', confirmed: true });
    await desktopApi.previewRollback('C:\\fake\\backup'); expect(mocks.invoke).toHaveBeenLastCalledWith('preview_rollback', { backupPath: 'C:\\fake\\backup' });
    await desktopApi.saveTemplate('fake-candidate', 'Fake template', ['/key'], '{}'); expect(mocks.invoke).toHaveBeenLastCalledWith('save_template', { candidateId: 'fake-candidate', name: 'Fake template', selectedPointers: ['/key'], schema: '{}' });
  });
  it('opens only a single explicit file picker and treats cancel as null', async () => {
    expect(await desktopApi.pickFile()).toBeNull(); expect(mocks.open).toHaveBeenCalledWith(expect.objectContaining({ multiple: false, directory: false }));
    mocks.open.mockResolvedValue('C:\\fake\\config.jsonc'); expect(await desktopApi.pickFile()).toBe('C:\\fake\\config.jsonc');
    mocks.open.mockResolvedValue(['unexpected-a', 'unexpected-b']); expect(await desktopApi.pickFile()).toBeNull();
  });
});
