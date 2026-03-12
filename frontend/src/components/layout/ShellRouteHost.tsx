import type { ChatPanelType } from '@/stores';

interface ShellRouteHostProps {
  overlay: Exclude<ChatPanelType, 'none'>;
}

const ShellRouteHost = ({ overlay }: ShellRouteHostProps) => (
  <div className="h-full" data-testid={`shell-route-${overlay}`} aria-label={overlay} />
);

export default ShellRouteHost;
