/**
 * Per-provider recommended models for the three built-in LLM scenarios.
 *
 * Used by the folded LLM Setup step in onboarding to pre-populate model
 * selections when a user picks a known provider. Providers that don't ship
 * a native embedding model (e.g. Anthropic) declare `embedding: null` —
 * the UI must surface a separate embedding-provider configuration in that
 * case.
 *
 * Provider IDs match the keys used in the backend LLM provider registry.
 */

export interface RecommendedModelSet {
  /** Fast / cheap classifier-style model. */
  context_decider: string;
  /** Primary generation model used for chat. */
  core: string;
  /** Embedding model id, or null if the provider has no native embeddings. */
  embedding: string | null;
}

export const RECOMMENDED_MODELS: Record<string, RecommendedModelSet> = {
  anthropic: {
    context_decider: 'claude-haiku-4-5',
    core: 'claude-sonnet-4-5',
    embedding: null,
  },
  openai: {
    context_decider: 'gpt-4o-mini',
    core: 'gpt-4o',
    embedding: 'text-embedding-3-small',
  },
  openrouter: {
    context_decider: 'anthropic/claude-haiku-4-5',
    core: 'anthropic/claude-sonnet-4-5',
    embedding: 'openai/text-embedding-3-small',
  },
  deepseek: {
    context_decider: 'deepseek-v4-flash',
    core: 'deepseek-v4-pro',
    embedding: null,
  },
};

/** Returns the recommended set for `providerId`, or undefined if unknown. */
export function getRecommendedModels(providerId: string): RecommendedModelSet | undefined {
  return RECOMMENDED_MODELS[providerId];
}
