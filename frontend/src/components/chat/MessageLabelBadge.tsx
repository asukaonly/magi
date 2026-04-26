import type { ChatTimelineMessageLabel } from '@/domain/chat/state';

type MessageLabelBadgeProps = {
  align: 'user' | 'assistant';
  label?: ChatTimelineMessageLabel | null;
  showLabel: boolean;
};

export const MessageLabelBadge = ({ align, label, showLabel }: MessageLabelBadgeProps) => {
  if (!showLabel || !label) {
    return null;
  }

  return (
    <div className={`mt-2 flex ${align === 'user' ? 'justify-end' : 'justify-start'}`}>
      <span className="inline-flex h-7 min-w-7 items-center justify-center rounded-full border border-border/60 bg-background px-2 text-sm shadow-sm">
        {label.text}
      </span>
    </div>
  );
};