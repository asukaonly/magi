import { Activity, icons as lucideIcons, type LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

interface PluginIconProps {
  iconId?: string | null;
  className?: string;
}

const SAFE_IMAGE_DATA_URI = /^data:image\/(?:svg\+xml|png|webp);base64,[a-z0-9+/=]+$/i;

const lucideExportName = (iconName: string): string =>
  iconName
    .split('-')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('');

const resolveLucideIcon = (iconId: string): LucideIcon | null => {
  if (!iconId.startsWith('lucide:')) return null;
  const exportName = lucideExportName(iconId.slice('lucide:'.length).trim().toLowerCase());
  if (!exportName) return null;
  return (lucideIcons[exportName as keyof typeof lucideIcons] as LucideIcon | undefined) ?? null;
};

export function PluginIcon({
  iconId,
  className,
}: PluginIconProps): JSX.Element {
  const baseClassName = cn('h-4 w-4', className);
  const normalizedIconId = String(iconId || '').trim();

  if (SAFE_IMAGE_DATA_URI.test(normalizedIconId)) {
    return (
      <img
        data-testid="plugin-icon-asset"
        src={normalizedIconId}
        alt=""
        aria-hidden="true"
        draggable={false}
        className={cn(baseClassName, 'object-contain')}
      />
    );
  }

  const Icon = resolveLucideIcon(normalizedIconId) ?? Activity;
  return <Icon data-testid="plugin-icon-fallback" className={baseClassName} aria-hidden="true" />;
}
