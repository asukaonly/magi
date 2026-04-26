import type { ReactNode } from 'react';
import { motion } from 'framer-motion';
import type { ChatTimelineMessage } from '@/domain/chat/state';

type RuntimeStatusCardProps = {
  message: ChatTimelineMessage;
  shouldReduceMotion: boolean;
  avatar: ReactNode;
  executionPanel: ReactNode;
};

export const RuntimeStatusCard = ({
  message,
  shouldReduceMotion,
  avatar,
  executionPanel,
}: RuntimeStatusCardProps) => {
  const turnId = String(message.turnId || '').trim();

  return (
    <motion.div
      key={message.id}
      initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: shouldReduceMotion ? 0 : 0.2, ease: 'easeOut' }}
      className="mb-4 flex justify-start"
      data-testid={turnId ? `chat-trace-status-card-${turnId}` : undefined}
    >
      <div className="flex max-w-[76%] gap-3">
        {avatar}
        <div className="rounded-xl rounded-tl-sm border border-border/35 bg-muted/35 px-4 py-2.5">
          {executionPanel}
        </div>
      </div>
    </motion.div>
  );
};