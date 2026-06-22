import { describe, expect, it } from 'vitest';
import enOnboarding from '@/i18n/locales/en/onboarding.json';
import zhCnOnboarding from '@/i18n/locales/zh-CN/onboarding.json';

describe('LLM provider billing copy', () => {
  it('labels provider pricing choices as billing modes', () => {
    expect(zhCnOnboarding.llm.fields.providerPlan).toBe('计费方式');
    expect(zhCnOnboarding.llm.providerPlans.default).toBe('API 计费');
    expect(enOnboarding.llm.fields.providerPlan).toBe('Billing mode');
    expect(enOnboarding.llm.providerPlans.default).toBe('API billing');
  });
});
