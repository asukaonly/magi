import type { SystemConfig } from '@/api/modules/config';

export type ToolValidationField =
  | 'weather.apiKey'
  | 'weather.apiUrl'
  | 'webSearch.apiKey';

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
    if (!hasText(weather.apiKey)) {
      issues.push({
        field: 'weather.apiKey',
        messageKey: 'tools.validation.weatherApiKeyRequired',
      });
    }
    if (weather.provider === 'qweather' && !hasText(weather.apiUrl)) {
      issues.push({
        field: 'weather.apiUrl',
        messageKey: 'tools.validation.qweatherApiUrlRequired',
      });
    }
  }

  const webSearch = builtIn.webSearch;
  if (webSearch?.enabled && webSearch.provider !== 'duckduckgo' && !hasText(webSearch.apiKey)) {
    issues.push({
      field: 'webSearch.apiKey',
      messageKey: 'tools.validation.webSearchApiKeyRequired',
      values: {
        provider: WEB_SEARCH_PROVIDER_LABELS[webSearch.provider] || webSearch.provider,
      },
    });
  }

  return issues;
}