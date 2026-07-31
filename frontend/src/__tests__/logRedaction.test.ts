import { describe, expect, it } from 'vitest';

import {
  LOG_REDACTED_VALUE,
  isSensitiveLogField,
  redactConsoleArgs,
  redactLogText,
  redactLogValue,
  registerKnownLogSecrets,
} from '@/runtime/log-redaction';

describe('desktop log redaction', () => {
  it('masks structured credentials while retaining token metrics', () => {
    const redacted = redactLogValue({
      'api-key': 'api-secret',
      nested: {
        accessToken: 'access-secret',
        proxy_password: 'proxy-secret',
      },
      input_tokens: 42,
      max_output_tokens: 512,
      private_network_allowlist: ['127.0.0.1'],
    }) as Record<string, any>;

    expect(redacted['api-key']).toBe(LOG_REDACTED_VALUE);
    expect(redacted.nested.accessToken).toBe(LOG_REDACTED_VALUE);
    expect(redacted.nested.proxy_password).toBe(LOG_REDACTED_VALUE);
    expect(redacted.input_tokens).toBe(42);
    expect(redacted.max_output_tokens).toBe(512);
    expect(redacted.private_network_allowlist).toEqual(['127.0.0.1']);
  });

  it('masks headers, URLs, assignments, and high-confidence token formats', () => {
    const providerToken = 'sk-proj-abcdefghijklmnopqrstuvwxyz123456';
    const redacted = redactLogText([
      'Authorization: Bearer auth-secret',
      'https://user:proxy-pass@example.test/path?api_key=query-secret&mode=debug',
      '{"client_secret":"json-secret","input_tokens":42}',
      'headers={"Cookie":"session=dict-cookie-secret"}',
      '{"authorization":"Custom json-auth-secret"}',
      'cookie=assignment-cookie-secret',
      'authorization=assignment-auth-secret',
      'pwd=assignment-pwd-secret',
      'bearer=assignment-bearer-secret',
      `provider=${providerToken}`,
      'token budget remains useful',
    ].join('\n'));

    for (const secret of [
      'auth-secret',
      'proxy-pass',
      'query-secret',
      'json-secret',
      'dict-cookie-secret',
      'json-auth-secret',
      'assignment-cookie-secret',
      'assignment-auth-secret',
      'assignment-pwd-secret',
      'assignment-bearer-secret',
      providerToken,
    ]) {
      expect(redacted).not.toContain(secret);
    }
    expect(redacted).toContain('mode=debug');
    expect(redacted).toContain('"input_tokens":42');
    expect(redacted).toContain('token budget remains useful');
  });

  it('redacts configured secrets in raw and URL-encoded forms', () => {
    registerKnownLogSecrets({
      providers: {
        custom: {
          api_key: 'frontend secret/+value',
        },
      },
    });

    const redacted = redactLogText(
      'plain=frontend secret/+value encoded=frontend%20secret%2F%2Bvalue',
    );

    expect(redacted).not.toContain('frontend secret/+value');
    expect(redacted).not.toContain('frontend%20secret%2F%2Bvalue');
    expect(redacted.match(/\[REDACTED\]/g)).toHaveLength(2);
  });

  it('hides short configured secrets even when embedded in text', () => {
    registerKnownLogSecrets({ proxy: { password: 'x7!' } });

    expect(redactLogText('prefix-x7!-suffix')).toBe('prefix-[REDACTED]-suffix');
  });

  it('keeps ordinary words readable for one-character secrets', () => {
    registerKnownLogSecrets({ proxy: { password: 'q' } });

    expect(redactLogText('q request quality')).toBe('[REDACTED] request quality');
  });

  it('does not register a mask placeholder as a secret', () => {
    registerKnownLogSecrets({ api_key: '***' });

    expect(redactLogText('separator *** remains visible')).toBe(
      'separator *** remains visible',
    );
  });

  it('masks signed URL credentials', () => {
    const redacted = redactLogText(
      'https://example.test/file?X-Amz-Credential=temp-access&X-Amz-Signature=temp-signature&mode=view',
    );

    expect(redacted).not.toContain('temp-access');
    expect(redacted).not.toContain('temp-signature');
    expect(redacted).toContain('mode=view');
  });

  it('masks sibling values when a config path identifies a secret', () => {
    expect(redactLogValue({
      path: 'llm.providers.primary.api_key',
      value: 'path-secret',
      operation: 'replace',
    })).toEqual({
      path: 'llm.providers.primary.api_key',
      value: LOG_REDACTED_VALUE,
      operation: 'replace',
    });
  });

  it('sanitizes Error objects and inline binary data', () => {
    const image = 'A'.repeat(96);
    const args = redactConsoleArgs([
      new Error('request failed token=error-secret'),
      `data:image/png;base64,${image}`,
    ]);
    const rendered = JSON.stringify(args);

    expect(rendered).not.toContain('error-secret');
    expect(rendered).not.toContain(image);
    expect(rendered).toContain('binary content omitted');
  });

  it('does not classify normal token diagnostics as secrets', () => {
    expect(isSensitiveLogField('refresh-token')).toBe(true);
    expect(isSensitiveLogField('providerApiKey')).toBe(true);
    expect(isSensitiveLogField('max_tokens')).toBe(false);
    expect(isSensitiveLogField('tokenizer')).toBe(false);
    expect(isSensitiveLogField('private_network_allowlist')).toBe(false);
  });
});
