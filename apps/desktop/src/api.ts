import { invoke } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-dialog';
import type { DesktopApi } from './types';

/** No fetch, storage, clipboard, telemetry, or generic filesystem bridge. */
export const desktopApi: DesktopApi = {
  initializeStorage: (confirmed) => invoke('initialize_storage', { confirmed }),
  configureCodexCli: (cliPath, profilePath, confirmed) => invoke('configure_codex_cli', { cliPath, profilePath, confirmed }),
  disconnectCodexCli: () => invoke('disconnect_codex_cli'),
  queryCodexUsage: (confirmed) => invoke('query_codex_usage', { confirmed }),
  queryGlmUsage: (region, planKind, keyId, confirmed) => invoke('query_glm_usage', { region, planKind, keyId, confirmed }),
  harnessStatus: () => invoke('harness_status'),
  harnessDiagnose: (operation) => invoke('harness_diagnose', { operation }),
  harnessCapabilities: () => invoke('harness_capabilities'),
  harnessExecute: (operation, harnesses, confirmed) => invoke('harness_execute', { operation, harnesses, confirmed }),
  skillsInventory: () => invoke('skills_inventory'),
  skillsInstall: (sourcePath, rootId, name, confirmed) => invoke('skills_install', { sourcePath, rootId, name, confirmed }),
  skillsUninstall: (rootId, name, confirmed) => invoke('skills_uninstall', { rootId, name, confirmed }),
  skillsRestore: (trashId, confirmed) => invoke('skills_restore', { trashId, confirmed }),
  skillsPurge: (trashId, confirmed) => invoke('skills_purge', { trashId, confirmed }),
  skillsCopy: (sourceRoot, name, targetRoot, confirmed) => invoke('skills_copy', { sourceRoot, name, targetRoot, confirmed }),
  pickDirectory: async () => {
    const selected = await open({ multiple: false, directory: true, title: '选择包含 SKILL.md 的本机技能文件夹' });
    return typeof selected === 'string' ? selected : null;
  },
  snapshot: () => invoke('snapshot'),
  saveKey: (id, name, secret) => invoke('save_key', { id, name, secret }),
  deleteKey: (id) => invoke('delete_key', { id }),
  saveTarget: (target) => invoke('save_target', { target }),
  deleteTarget: (id) => invoke('delete_target', { id }),
  preview: (selected) => invoke('preview', { selected }),
  applyPreview: (id, confirmed) => invoke('apply_preview', { id, confirmed }),
  cancelPreview: () => invoke('cancel_preview'),
  listBackups: () => invoke('list_backups'),
  previewRollback: (backupPath) => invoke('preview_rollback', { backupPath }),
  inferTemplate: (filePath) => invoke('infer_template', { filePath }),
  saveTemplate: (candidateId, name, selectedPointers, schema) => invoke('save_template', { candidateId, name, selectedPointers, schema: schema ?? null }),
  deleteTemplate: (id) => invoke('delete_template', { id }),
  pickFile: async () => {
    const selected = await open({ multiple: false, directory: false, title: '选择已知的本机 JSON / JSONC 配置文件', filters: [{ name: 'JSON / JSONC', extensions: ['json', 'jsonc'] }] });
    return typeof selected === 'string' ? selected : null;
  },
};

