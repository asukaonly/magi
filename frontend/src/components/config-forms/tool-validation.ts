import type { SystemConfig } from '@/api/modules/config';

export type ToolValidationField =
  | 'weather.apiKey'
  | 'webSearch.apiKey'
  | 'webSearch.apiUrl';

export interface ToolValidationIssue {
  field: ToolValidationField;
  messageKey: string;
  values?: Record<string, string>;
}

const WEB_SEARCH_PROVIDER_LABELS: Record<string, string> = {
  brave: 'Brave',
  perplexity: 'Perplexity',
  tavily: 'Tavily',
};

const hasText = (value: unknown): boolean => String(value ?? '').trim().length > 0;

export function validateToolsConfig(config?: Pick<SystemConfig, 'tools'> | null): ToolValidationIssue[] {
  const issues: ToolValidationIssue[] = [];
  const builtIn = config?.tools?.builtIn;
  if (!builtIn) {
    return issues;
  }

  const weather = builtIn.weather;
  if (weather?.enabled) {
    if (weather.provider === 'qweather' && !hasText(weather.apiKey)) {
      issues.push({
        field: 'weather.apiKey',
        messageKey: 'tools.validation.weatherApiKeyRequired',
      });
    }
  }

  const webSearch = builtIn.webSearch;
  if (webSearch?.enabled) {
    if (webSearch.provider === 'searxng' && !hasText(webSearch.apiUrl)) {
      issues.push({
        field: 'webSearch.apiUrl',
        messageKey: 'tools.validation.webSearchApiUrlRequired',
      });
    } else if (webSearch.provider !== 'duckduckgo' && webSearch.provider !== 'searxng' && !hasText(webSearch.apiKey)) {
      issues.push({
        field: 'webSearch.apiKey',
        messageKey: 'tools.validation.webSearchApiKeyRequired',
        values: {
          provider: WEB_SEARCH_PROVIDER_LABELS[webSearch.provider] || webSearch.provider,
        },
      });
    }
  }

  return issues;
}