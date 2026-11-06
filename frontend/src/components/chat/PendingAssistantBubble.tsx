import { motion } from 'framer-motion';
import { ChatRoleAvatar } from './ChatRoleAvatar';
import { ChatProgressDots } from './ChatProgressDots';

type PendingAssistantBubbleProps = {
  assistantName: string;
  assistantAvatar: string;
  shouldReduceMotion: boolean;
};

/**
 * Placeholder bubble shown between "user pressed send" and "first assistant
 * chunk arrives". Without it, the UI looks frozen during the 1–3s the LLM
 * spends in routing + first-token latency. The bubble itself is replaced
 * (visually, not in state) by the streaming bubble once the first
 * agent_response_chunk lands — there's nothing to remove, just stop
 * rendering this component as soon as a streaming/persisted assistant
 * message exists for the active turn.
 *
 * The bubble layout mirrors TranscriptTimelineMessage's assistant variant
 * so the visual swap is seamless; only the dots animate.
 */
export const PendingAssistantBubble = ({
  assistantName,
  assistantAvatar,
  shouldReduceMotion,
}: PendingAssistantBubbleProps) => (
  <motion.div
    initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: shouldReduceMotion ? 0 : 0.2, ease: 'easeOut' }}
    className="group/message mb-5 flex justify-start"
  >
    <div className="flex max-w-[75%] gap-3">
      <ChatRoleAvatar
        role="assistant"
        assistantName={assistantName}
        assistantAvatar={assistantAvatar}
        avatarState={shouldReduceMotion ? 'idle' : 'streaming'}
      />
      <div className="flex flex-col items-start">
        <div className="mb-1 flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">{assistantName}</span>
        </div>
        <div
          className={
            'w-fit max-w-full rounded-xl rounded-tl-sm border border-border/55 bg-card px-4 py-3 shadow-xs'
          }
        >
          <ChatProgressDots shouldReduceMotion={shouldReduceMotion} />
        </div>
      </div>
    </div>
  </motion.div>
);
