import { describe, expect, it } from 'vitest';

import { validateToolsConfig } from '@/components/config-forms/tool-validation';

describe('validateToolsConfig', () => {
  it('does not require weather credentials for Open-Meteo', () => {
    const issues = validateToolsConfig({
      tools: {
        builtIn: {
          weather: { enabled: true, provider: 'openmeteo' },
          webSearch: { enabled: false, provider: 'duckduckgo' },
          webFetch: { enabled: true, allowRfc2544BenchmarkRange: true },
        },
        skills: [],
      },
    });

    expect(issues).toEqual([]);
  });

  it('still requires QWeather API key when QWeather is selected', () => {
    const issues = validateToolsConfig({
      tools: {
        builtIn: {
          weather: { enabled: true, provider: 'qweather' },
          webSearch: { enabled: false, provider: 'duckduckgo' },
          webFetch: { enabled: true, allowRfc2544BenchmarkRange: true },
        },
        skills: [],
      },
    });

    expect(issues.map((issue) => issue.field)).toEqual(['weather.apiKey']);
  });

  it('requires a SearXNG instance URL instead of an API key', () => {
    const missingUrl = validateToolsConfig({
      tools: {
        builtIn: {
          weather: { enabled: false, provider: 'openmeteo' },
          webSearch: { enabled: true, provider: 'searxng' },
          webFetch: { enabled: true, allowRfc2544BenchmarkRange: true },
        },
        skills: [],
      },
    });

    const configured = validateToolsConfig({
      tools: {
        builtIn: {
          weather: { enabled: false, provider: 'openmeteo' },
          webSearch: { enabled: true, provider: 'searxng', apiUrl: 'https://search.example.com' },
          webFetch: { enabled: true, allowRfc2544BenchmarkRange: true },
        },
        skills: [],
      },
    });

    expect(missingUrl.map((issue) => issue.field)).toEqual(['webSearch.apiUrl']);
    expect(configured).toEqual([]);
  });
});
