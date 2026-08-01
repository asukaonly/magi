import { api, resolveApiBaseUrl } from '../client';
import {
  captureBrowserContentGeneration,
  isBrowserContentGenerationCurrent,
} from '@/lib/browserContentGeneration';

export type PrivateResourceDescriptor =
  | {
    kind: 'chat_attachment';
    user_id: string;
    session_id: string;
    attachment_id: string;
  }
  | {
    kind: 'timeline_asset';
    asset_ref: string;
  }
  | {
    kind: 'user_avatar';
    filename: string;
  };

type PrivateResourceGrant = {
  access_url: string;
  expires_at_ms: number;
};

type CachedGrant = {
  url: string;
  expiresAtMs: number;
};

const MIN_REMAINING_LIFETIME_MS = 5_000;
const MAX_CACHED_GRANTS = 512;
const cachedGrants = new Map<string, CachedGrant>();
const pendingGrants = new Map<string, Promise<CachedGrant>>();
let accessGeneration = 0;

function gatewayOrigin(): string {
  return resolveApiBaseUrl().replace(/\/api\/?$/, '');
}

function descriptorKey(descriptor: PrivateResourceDescriptor): string {
  switch (descriptor.kind) {
    case 'chat_attachment':
      return `chat:${descriptor.user_id}:${descriptor.session_id}:${descriptor.attachment_id}`;
    case 'timeline_asset':
      return `timeline:${descriptor.asset_ref}`;
    case 'user_avatar':
      return `avatar:${descriptor.filename}`;
  }
}

function grantMatchesDescriptor(
  url: URL,
  descriptor: PrivateResourceDescriptor,
  key: string,
): boolean {
  const grantedDescriptor = parsePrivateResourceSource(url.toString());
  if (!grantedDescriptor || descriptorKey(grantedDescriptor) !== key) {
    return false;
  }

  const allowedQueryKeys = descriptor.kind === 'chat_attachment'
    ? new Set(['user_id', 'resource_ticket'])
    : new Set(['resource_ticket']);
  let hasUnexpectedQuery = false;
  url.searchParams.forEach((_value, queryKey) => {
    if (!allowedQueryKeys.has(queryKey)) {
      hasUnexpectedQuery = true;
    }
  });
  if (hasUnexpectedQuery) {
    return false;
  }

  const tickets = url.searchParams.getAll('resource_ticket');
  if (tickets.length !== 1 || !tickets[0]) {
    return false;
  }
  return descriptor.kind !== 'chat_attachment'
    || url.searchParams.getAll('user_id').length === 1;
}

function decodePathValue(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

export function parsePrivateResourceSource(
  source: string | null | undefined,
): PrivateResourceDescriptor | null {
  const value = String(source || '').trim();
  if (!value || value.startsWith('blob:') || value.startsWith('data:')) {
    return null;
  }

  let url: URL;
  try {
    url = new URL(value, `${gatewayOrigin()}/`);
  } catch {
    return null;
  }

  if (url.origin !== new URL(gatewayOrigin()).origin) {
    return null;
  }

  const attachmentMatch = url.pathname.match(
    /^\/api\/messages\/session\/([^/]+)\/attachments\/([^/]+)\/content$/,
  );
  if (attachmentMatch) {
    const userId = url.searchParams.get('user_id')?.trim() || '';
    const sessionId = decodePathValue(attachmentMatch[1]);
    const attachmentId = decodePathValue(attachmentMatch[2]);
    if (userId && sessionId && attachmentId) {
      return {
        kind: 'chat_attachment',
        user_id: userId,
        session_id: sessionId,
        attachment_id: attachmentId,
      };
    }
  }

  const timelinePrefix = '/api/timeline/asset/';
  if (url.pathname.startsWith(timelinePrefix)) {
    const assetRef = decodePathValue(url.pathname.slice(timelinePrefix.length));
    if (assetRef) {
      return {
        kind: 'timeline_asset',
        asset_ref: assetRef,
      };
    }
  }

  const avatarMatch = url.pathname.match(/^\/static\/user-avatars\/([^/]+)$/);
  if (avatarMatch) {
    const filename = decodePathValue(avatarMatch[1]);
    if (filename) {
      return {
        kind: 'user_avatar',
        filename,
      };
    }
  }

  return null;
}

export function getCachedPrivateResourceUrl(
  descriptor: PrivateResourceDescriptor,
): string | null {
  const key = descriptorKey(descriptor);
  const cached = cachedGrants.get(key);
  if (!cached || cached.expiresAtMs - Date.now() <= MIN_REMAINING_LIFETIME_MS) {
    cachedGrants.delete(key);
    return null;
  }
  return cached.url;
}

export function invalidatePrivateResourceUrl(
  descriptor: PrivateResourceDescriptor,
): void {
  cachedGrants.delete(descriptorKey(descriptor));
}

export async function resolvePrivateResourceUrl(
  descriptor: PrivateResourceDescriptor,
  options: { force?: boolean } = {},
): Promise<string> {
  const key = descriptorKey(descriptor);
  const requestGeneration = accessGeneration;
  const browserContentGeneration = captureBrowserContentGeneration();
  if (options.force) {
    cachedGrants.delete(key);
  } else {
    const cached = getCachedPrivateResourceUrl(descriptor);
    if (cached) {
      return cached;
    }
  }

  const pending = pendingGrants.get(key);
  if (pending) {
    return (await pending).url;
  }

  const request = api
    .post<PrivateResourceGrant>('/private-resource-tickets', descriptor)
    .then((response) => {
      if (
        requestGeneration !== accessGeneration
        || !isBrowserContentGenerationCurrent(browserContentGeneration)
      ) {
        throw new Error('Private resource access request was retired');
      }
      const grant = response.data;
      if (
        !grant
        || typeof grant.access_url !== 'string'
        || !grant.access_url.startsWith('/')
        || grant.access_url.startsWith('//')
        || !Number.isFinite(grant.expires_at_ms)
        || grant.expires_at_ms <= Date.now()
      ) {
        throw new Error('Private resource access response is invalid');
      }
      const origin = gatewayOrigin();
      const resolvedUrl = new URL(grant.access_url, `${origin}/`);
      if (
        resolvedUrl.origin !== new URL(origin).origin
        || !grantMatchesDescriptor(resolvedUrl, descriptor, key)
      ) {
        throw new Error('Private resource access response is invalid');
      }
      const cachedGrant = {
        url: resolvedUrl.toString(),
        expiresAtMs: grant.expires_at_ms,
      };
      while (cachedGrants.size >= MAX_CACHED_GRANTS) {
        const oldest = cachedGrants.keys().next().value as string | undefined;
        if (!oldest) break;
        cachedGrants.delete(oldest);
      }
      cachedGrants.set(key, cachedGrant);
      return cachedGrant;
    })
    .finally(() => {
      if (pendingGrants.get(key) === request) {
        pendingGrants.delete(key);
      }
    });

  pendingGrants.set(key, request);
  return (await request).url;
}

export function clearPrivateResourceAccessCache(): boolean {
  accessGeneration += 1;
  cachedGrants.clear();
  pendingGrants.clear();
  return cachedGrants.size === 0 && pendingGrants.size === 0;
}
