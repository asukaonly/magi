import { afterEach, describe, expect, it, vi } from 'vitest';
import examples from '../../../contracts/api/frontend-config-examples.json';
import { api } from '@/api/client';
import { ApiContractError, parseConfigResponse, parseOnboardingStatusResponse, parseOnboardingTemplateResponse } from '@/api/config-contract';
import { configApi } from '@/api/modules/config';

afterEach(() => vi.restoreAllMocks());

describe('production configuration contracts', () => {
  it('reads actual Pydantic serialization including nullable credentials and defaults', () => {
    const response = parseConfigResponse(examples.config);
    expect(response.success).toBe(true);
    expect(response.data?.llm.providers.openai.api_key).toBeUndefined();
    expect(response.data?.llm.selections.core.model).toBe('fixture-model');
    expect(response.data?.memory.entity_semantic_edges).toEqual({ enabled: false });
    expect(response.data?.memory.reranker.cross_encoder).not.toHaveProperty('variant');
    expect(parseOnboardingStatusResponse(examples.onboardingStatus).data).toEqual({ completed: false });
    expect(parseOnboardingTemplateResponse(examples.onboardingTemplate).data?.config).toEqual(response.data);
  });

  it.each([
    ['missing envelope', examples.config.data],
    ['missing success data', { ...examples.config, data: null }],
    ['missing required field', { ...examples.config, data: { ...examples.config.data, llm: undefined } }],
    ['wrong nested type', { ...examples.config, data: { ...examples.config.data, network: { ...examples.config.data.network, enabled: 'yes' } } }],
    ['out of range', { ...examples.config, data: { ...examples.config.data, network: { ...examples.config.data.network, port: 70000 } } }],
    ['invalid enum', { ...examples.config, data: { ...examples.config.data, memory: { ...examples.config.data.memory, history_behavior: 'erase-everything' } } }],
    ['incomplete selections', { ...examples.config, data: { ...examples.config.data, llm: { ...examples.config.data.llm, selections: {} } } }],
    ['invalid dynamic modifiers', { ...examples.config, data: { ...examples.config.data, personality: { ...examples.config.data.personality, persona_layers: [{ layer_id: 'test', unlock_condition: null, modifiers: { humor_delta: 'high' } }] } } }],
  ])('rejects %s without presenting it as empty configuration', (_name, value) => {
    expect(() => parseConfigResponse(value)).toThrow(ApiContractError);
  });

  it('retains explicit server failure instead of manufacturing a successful default', () => {
    expect(parseConfigResponse(examples.failure)).toEqual({ success: false, message: 'Configuration unavailable', data: undefined });
  });

  it('does not include response contents in contract errors', () => {
    const invalid = structuredClone(examples.config);
    invalid.data.llm.providers.openai.provider_type = 'secret-must-not-leak';
    try {
      parseConfigResponse(invalid);
      expect.fail('Expected contract rejection');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiContractError);
      expect(String(error)).not.toContain('secret-must-not-leak');
    }
  });

  it('validates at the API entry before returning to callers', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce(examples.config).mockResolvedValueOnce({ success: true, message: 'OK', data: {} });
    await expect(configApi.get()).resolves.toMatchObject({ success: true, data: { agent: { name: 'magi-agent' } } });
    expect(api.get).toHaveBeenCalledWith('/config/');
    await expect(configApi.get()).rejects.toBeInstanceOf(ApiContractError);
  });

  it('validates save responses and onboarding completion responses', async () => {
    vi.spyOn(api, 'put').mockResolvedValue({ success: true, message: 'OK', data: {} });
    vi.spyOn(api, 'post').mockResolvedValue({ success: true, message: 'OK', data: {} });
    const config = parseConfigResponse(examples.config).data;
    if (!config) throw new Error('Production fixture is missing data');
    await expect(configApi.update(config)).rejects.toBeInstanceOf(ApiContractError);
    await expect(configApi.completeOnboarding({ revision: 'a'.repeat(64), language: 'en', llm: config.llm })).rejects.toBeInstanceOf(ApiContractError);
  });

  it('rejects incomplete onboarding responses', () => {
    expect(() => parseOnboardingStatusResponse({ success: true, message: 'OK', data: {} })).toThrow(ApiContractError);
    expect(() => parseOnboardingTemplateResponse({ success: true, message: 'OK', data: null })).toThrow(ApiContractError);
  });
});
