import { UserRound } from 'lucide-react';
import { getRuntimeConfig } from '@/runtime/config';

type ChatRoleAvatarProps = {
  role: 'user' | 'assistant';
  assistantName: string;
  assistantAvatar: string;
};

export const ChatRoleAvatar = ({
  role,
  assistantName,
  assistantAvatar,
}: ChatRoleAvatarProps) => {
  if (role === 'user') {
    return (
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border/55 bg-card text-muted-foreground shadow-sm">
        <UserRound className="h-4 w-4" />
      </div>
    );
  }

  const initial = assistantName?.charAt(0)?.toUpperCase() || 'A';
  let avatarSrc = assistantAvatar;
  if (avatarSrc && avatarSrc.startsWith('/')) {
    const apiBaseUrl = getRuntimeConfig().apiBaseUrl;
    const baseUrl = apiBaseUrl.replace(/\/api\/?$/, '');
    avatarSrc = `${baseUrl}${avatarSrc}`;
  }

  if (avatarSrc && avatarSrc.startsWith('http')) {
    return (
      <div className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-700">
        <img src={avatarSrc} alt={assistantName} className="h-full w-full object-cover" />
      </div>
    );
  }

  return (
    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
      {assistantAvatar || initial}
    </div>
  );
};