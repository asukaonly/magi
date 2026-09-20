/** Minimal advisory facts from the sending client, never an authorization identity. */
export interface ClientEnvironment {
  timezone: string | null;
  os: 'macos' | 'windows' | 'linux' | 'ios' | 'android' | 'unknown';
}

export function captureClientEnvironment(): ClientEnvironment {
  let timezone: string | null = null;
  try {
    timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    // Missing browser timezone data must not prevent a message from being sent.
  }
  const userAgent = typeof navigator === 'undefined' ? '' : navigator.userAgent;
  let os: ClientEnvironment['os'] = 'unknown';
  if (/Android/i.test(userAgent)) os = 'android';
  else if (/iPhone|iPad|iPod/i.test(userAgent)) os = 'ios';
  else if (/Windows/i.test(userAgent)) os = 'windows';
  else if (/Macintosh|Mac OS X/i.test(userAgent)) os = 'macos';
  else if (/Linux/i.test(userAgent)) os = 'linux';
  return { timezone, os };
}
