import { describe, expect, it } from 'vitest';
import {
  RECOMMENDED_MODELS,
  getRecommendedModels,
  type RecommendedModelSet,
} from '../constants/llm';

describe('RECOMMENDED_MODELS', () => {
  it('exposes recommendations for known providers', () => {
    expect(RECOMMENDED_MODELS.anthropic).toBeDefined();
    expect(RECOMMENDED_MODELS.openai).toBeDefined();
    expect(RECOMMENDED_MODELS.openrouter).toBeDefined();
    expect(RECOMMENDED_MODELS.deepseek).toBeDefined();
  });

  it('every recommendation includes core + context_decider; embedding may be null', () => {
    for (const [providerId, recs] of Object.entries(RECOMMENDED_MODELS)) {
      expect(recs.core, `${providerId}.core`).toBeTypeOf('string');
      expect(recs.context_decider, `${providerId}.context_decider`).toBeTypeOf('string');
      // embedding may be null when the provider has no native embedding model
      const emb = recs.embedding;
      expect(emb === null || typeof emb === 'string', `${providerId}.embedding`).toBe(true);
    }
  });

  it('Anthropic intentionally has null embedding (no native embedding model)', () => {
    expect(RECOMMENDED_MODELS.anthropic.embedding).toBeNull();
  });

  it('OpenAI ships a full set including embedding', () => {
    expect(RECOMMENDED_MODELS.openai.embedding).not.toBeNull();
  });

  it('getRecommendedModels returns undefined for unknown providers', () => {
    expect(getRecommendedModels('unknown-provider' as any)).toBeUndefined();
  });

  it('getRecommendedModels returns the typed set for known providers', () => {
    const set: RecommendedModelSet | undefined = getRecommendedModels('openai');
    expect(set?.core).toBeTypeOf('string');
  });
});
