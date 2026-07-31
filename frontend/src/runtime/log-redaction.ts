const REDACTED = '[REDACTED]';
const OMITTED = '[binary content omitted]';

const NON_SECRET_TOKEN_FIELDS = new Set([
  'cached_tokens',
  'completion_tokens',
  'input_tokens',
  'max_output_tokens',
  'max_tokens',
  'output_tokens',
  'prompt_tokens',
  'reasoning_tokens',
  'token_budget',
  'token_count',
  'token_counts',
  'token_limit',
  'token_usage',
  'total_tokens',
]);

const EXACT_SENSITIVE_FIELDS = new Set([
  'api_key',
  'apikey',
  'auth',
  'authorization',
  'bearer',
  'client_secret',
  'cookie',
  'credential',
  'credentials',
  'password',
  'passwd',
  'private_key',
  'proxy_authorization',
  'pwd',
  'secret',
  'set_cookie',
  'sig',
  'signature',
  'signing_key',
  'token',
]);

const knownSecrets = new Set<string>();

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function normalizeFieldName(fieldName: string): string {
  return fieldName
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

export function isSensitiveLogField(fieldName: string): boolean {
  const normalized = normalizeFieldName(fieldName);
  if (!normalized || NON_SECRET_TOKEN_FIELDS.has(normalized)) return false;
  if (EXACT_SENSITIVE_FIELDS.has(normalized)) return true;
  if (
    [
      '_api_key',
      '_auth_token',
      '_bot_token',
      '_client_secret',
      '_credential',
      '_credentials',
      '_password',
      '_private_key',
      '_refresh_token',
      '_secret',
      '_session_token',
      '_signature',
      '_signing_key',
    ].some((suffix) => normalized.endsWith(suffix))
  ) {
    return true;
  }
  if (normalized.endsWith('_token')) return true;
  return normalized.split('_').includes('secret');
}

function collectSensitiveValues(
  value: unknown,
  sensitiveParent: boolean,
  seen: WeakSet<object>,
  collected: Set<string>,
): void {
  if (typeof value === 'string') {
    if (sensitiveParent && value) collected.add(value);
    return;
  }
  if (value === null || typeof value !== 'object') return;
  if (seen.has(value)) return;
  seen.add(value);

  if (Array.isArray(value)) {
    for (const item of value) collectSensitiveValues(item, sensitiveParent, seen, collected);
    return;
  }
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    collectSensitiveValues(
      item,
      sensitiveParent || isSensitiveLogField(key),
      seen,
      collected,
    );
  }
}

export function registerKnownLogSecrets(value: unknown): void {
  const collected = new Set<string>();
  collectSensitiveValues(value, false, new WeakSet(), collected);
  for (const secret of collected) {
    if (/^(?:\*{3,}|•{3,})$/.test(secret)) continue;
    knownSecrets.add(secret);
    try {
      knownSecrets.add(encodeURIComponent(secret));
      knownSecrets.add(new URLSearchParams({ value: secret }).toString().slice('value='.length));
    } catch {
      // The raw value remains registered.
    }
  }
}

function redactKnownSecrets(text: string): string {
  let redacted = text;
  const secrets = [...knownSecrets].sort((left, right) => right.length - left.length);
  for (const secret of secrets) {
    if (!secret || secret === REDACTED || secret === OMITTED) continue;
    if (secret.length >= 6) {
      redacted = redacted.split(secret).join(REDACTED);
      continue;
    }
    redacted = redacted.replace(
      new RegExp(`(^|[^A-Za-z0-9])${escapeRegExp(secret)}(?=$|[^A-Za-z0-9])`, 'g'),
      (_match, prefix: string) => `${prefix}${REDACTED}`,
    );
  }
  return redacted;
}

export function redactLogText(value: string): string {
  let text = String(value);
  text = text.replace(
    /-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----[\s\S]*?-----END(?: [A-Z0-9]+)? PRIVATE KEY-----/g,
    REDACTED,
  );
  text = text.replace(
    /data:([a-z0-9.+-]+\/[a-z0-9.+-]+);base64,([a-z0-9+/=_-]{32,})/gi,
    (_match, mime: string, data: string) =>
      `data:${mime};base64,${OMITTED} (${data.length} chars)`,
  );
  text = redactKnownSecrets(text);
  text = text.replace(
    /\b(authorization|proxy-authorization)\s*:\s*[^\r\n]+/gi,
    (_match, name: string) => `${name}: ${REDACTED}`,
  );
  text = text.replace(
    /\b(cookie|set-cookie)\s*:\s*[^\r\n]+/gi,
    (_match, name: string) => `${name}: ${REDACTED}`,
  );
  text = text.replace(/\b(bearer|basic)\s+[a-z0-9._~+/=-]{3,}/gi, `$1 ${REDACTED}`);
  text = text.replace(
    /(["']?(?:(?:[a-z0-9]+[_-])*api[_-]?key|x[_-][a-z0-9_-]*api[_-]?key|access[_-]?token|auth|authorization|auth[_-]?token|bearer|bearer[_-]?token|bot[_-]?token|client[_-]?secret|cookie|(?:[a-z0-9]+[_-])*credential(?:s)?|password|passwd|private[_-]?key|proxy[_-]?authorization|pwd|refresh[_-]?token|secret|session[_-]?token|set[_-]?cookie|(?:[a-z0-9]+[_-])*signature|sig|signing[_-]?key|token)["']?\s*[:=]\s*)(["'])(.*?)\2/gi,
    `$1$2${REDACTED}$2`,
  );
  text = text.replace(
    /((?:(?:[a-z0-9]+[_-])*api[_-]?key|x[_-][a-z0-9_-]*api[_-]?key|access[_-]?token|auth|authorization|auth[_-]?token|bearer|bearer[_-]?token|bot[_-]?token|client[_-]?secret|cookie|(?:[a-z0-9]+[_-])*credential(?:s)?|password|passwd|private[_-]?key|proxy[_-]?authorization|pwd|refresh[_-]?token|secret|session[_-]?token|set[_-]?cookie|(?:[a-z0-9]+[_-])*signature|sig|signing[_-]?key|token)\s*[:=]\s*)[^\s,;&#}\])]+/gi,
    `$1${REDACTED}`,
  );
  text = text.replace(
    /([a-z][a-z0-9+.-]*:\/\/)([^/@:\s]+):([^/@\s]+)@/gi,
    `$1$2:${REDACTED}@`,
  );
  for (const pattern of [
    /\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}\b/g,
    /\bxai-[A-Za-z0-9_-]{16,}\b/g,
    /\bgh[pousr]_[A-Za-z0-9]{20,}\b/g,
    /\bAIza[0-9A-Za-z_-]{20,}\b/g,
    /\bhf_[A-Za-z0-9]{20,}\b/g,
    /\bxox[a-z]-[A-Za-z0-9-]{16,}\b/gi,
    /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g,
  ]) {
    text = text.replace(pattern, REDACTED);
  }
  return text;
}

export function redactLogValue(value: unknown, seen = new WeakSet<object>()): unknown {
  if (typeof value === 'string') return redactLogText(value);
  if (value === null || typeof value !== 'object') return value;
  if (value instanceof Error) {
    return redactLogText(`${value.name}: ${value.message}\n${value.stack ?? ''}`.trim());
  }
  if (seen.has(value)) return '[recursive value omitted]';
  seen.add(value);
  if (Array.isArray(value)) return value.map((item) => redactLogValue(item, seen));

  const record = value as Record<string, unknown>;
  const pathHint = ['path', 'field', 'field_name', 'setting', 'setting_path']
    .map((key) => record[key])
    .find((candidate) => typeof candidate === 'string' && isSensitiveLogField(candidate));
  return Object.fromEntries(
    Object.entries(record).map(([key, item]) => {
      const normalized = normalizeFieldName(key);
      const siblingValue = Boolean(pathHint) && [
        'current',
        'current_value',
        'new',
        'new_value',
        'old',
        'old_value',
        'value',
      ].includes(normalized);
      return [
        key,
        isSensitiveLogField(key) || siblingValue ? REDACTED : redactLogValue(item, seen),
      ];
    }),
  );
}

export function redactConsoleArgs(args: unknown[]): unknown[] {
  try {
    return args.map((item) => redactLogValue(item));
  } catch {
    return ['[log content omitted after redaction failure]'];
  }
}

export const LOG_REDACTED_VALUE = REDACTED;
