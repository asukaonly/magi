import { useEffect, useState } from 'react';
import { UserRound } from 'lucide-react';
import { getRuntimeConfig } from '@/runtime/config';
import { cn } from '@/lib/utils';
import { ProtectedImage } from '@/components/media/ProtectedImage';

export type ChatAvatarState = 'idle' | 'streaming' | 'failed' | 'static';

type ChatRoleAvatarProps = {
  role: 'user' | 'assistant';
  assistantName: string;
  assistantAvatar: string;
  /**
   * Lifecycle hint for the assistant avatar. `'static'` (or absent) renders
   * historical or non-active turns without any animation. `'idle'` shows a
   * slow breathing pulse to signal "the AI is here". `'streaming'` is a
   * faster pulse that reads as "actively thinking". `'failed'` paints a red
   * static halo. User avatars ignore this prop.
   */
  avatarState?: ChatAvatarState;
};

const resolveAvatarSrc = (assistantAvatar: string): string => {
  if (!assistantAvatar) {
    return '';
  }
  if (assistantAvatar.startsWith('/')) {
    const apiBaseUrl = getRuntimeConfig().apiBaseUrl;
    const baseUrl = apiBaseUrl.replace(/\/api\/?$/, '');
    return `${baseUrl}${assistantAvatar}`;
  }
  return assistantAvatar;
};

const canRenderImage = (src: string): boolean =>
  src.startsWith('http://') || src.startsWith('https://') || src.startsWith('data:image/');

export const ChatRoleAvatar = ({
  role,
  assistantName,
  assistantAvatar,
  avatarState = 'static',
}: ChatRoleAvatarProps) => {
  const avatarSrc = resolveAvatarSrc(assistantAvatar);
  const [avatarFailed, setAvatarFailed] = useState(false);

  useEffect(() => {
    setAvatarFailed(false);
  }, [avatarSrc]);

  if (role === 'user') {
    return (
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border/55 bg-card text-muted-foreground shadow-sm">
        <UserRound className="h-4 w-4" />
      </div>
    );
  }

  const initial = assistantName?.trim().charAt(0)?.toUpperCase() || 'A';

  // Only the lifecycle states emit a `data-avatar-state` attribute. Static
  // (historical) avatars render without any animation hook so they don't
  // distract from the active turn.
  const animatedState = avatarState === 'static' ? undefined : avatarState;

  const content = avatarSrc && canRenderImage(avatarSrc) && !avatarFailed ? (
    <div className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-700">
      <ProtectedImage
        src={avatarSrc}
        alt={assistantName}
        eager
        className="h-full w-full object-cover"
        onError={() => setAvatarFailed(true)}
        onProtectedAccessError={() => setAvatarFailed(true)}
      />
    </div>
  ) : (
    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
      {initial}
    </div>
  );

  return (
    <span
      className={cn('chat-avatar-shell h-9 w-9 shrink-0 self-start')}
      data-avatar-state={animatedState}
      aria-hidden="true"
    >
      {content}
    </span>
  );
};
