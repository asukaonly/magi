import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/api/client';
import { parseConfigResponse } from '@/api/config-contract';
import { configApi } from '@/api/modules/config';
import { DEFAULT_DEVICE_PREFERENCES, readDevicePreferences, writeDevicePreferences } from '@/runtime/device-preferences';
import { setCenterStorageScope } from '@/runtime/center-storage';
import fixtures from '../../../contracts/api/frontend-config-examples.json';

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

it('keeps device choices when switching centers or replacing center data', () => {
  writeDevicePreferences({ ...DEFAULT_DEVICE_PREFERENCES, auto_start_enabled: true });
  setCenterStorageScope('center-a', 'epoch-a');
  setCenterStorageScope('center-b', 'epoch-b');
  setCenterStorageScope('center-a', 'epoch-new');
  expect(readDevicePreferences().auto_start_enabled).toBe(true);
  expect(parseConfigResponse(fixtures.config).data?.preferences.auto_start_enabled).toBe(true);
});

it('does not transmit device preferences in a center configuration write', async () => {
  const put = vi.spyOn(api, 'put').mockResolvedValue(fixtures.config);
  const config = parseConfigResponse(fixtures.config).data!;
  config.preferences.auto_start_enabled = true;
  await configApi.update(config);
  const transmitted = put.mock.calls[0][1] as { preferences: Record<string, unknown> };
  expect(transmitted.preferences).toHaveProperty('default_chat_workspace_path');
  expect(transmitted.preferences).not.toHaveProperty('language');
  for (const key of Object.keys(DEFAULT_DEVICE_PREFERENCES)) expect(transmitted.preferences).not.toHaveProperty(key);
});

it("keeps device language when centers use different defaults", () => {
  localStorage.setItem("magi_language", "en");
  setCenterStorageScope("center-a", "epoch-a");
  expect(parseConfigResponse(fixtures.config).data?.preferences.language).toBe("en");
  setCenterStorageScope("center-b", "epoch-b");
  expect(parseConfigResponse(fixtures.config).data?.preferences.language).toBe("en");
});
