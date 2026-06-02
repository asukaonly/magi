import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { PendingAssistantBubble } from '@/components/chat/PendingAssistantBubble';

vi.mock('@/runtime/config', () => ({
  getRuntimeConfig: () => ({ apiBaseUrl: 'http://localhost/api' }),
}));

describe('PendingAssistantBubble', () => {
  it('renders an aria-labelled placeholder with three pulsing dots', () => {
    const { container } = render(
      <PendingAssistantBubble
        assistantName="Magi"
        assistantAvatar=""
        shouldReduceMotion={false}
      />,
    );

    // The placeholder bubble announces itself for screen readers.
    expect(
      screen.getByLabelText('Assistant is preparing a response'),
    ).toBeInTheDocument();

    // Three dots, one per cycle slot. We rely on the inline `animation`
    // style to drive the pulse — assert that each dot has it.
    const dots = container.querySelectorAll<HTMLSpanElement>(
      'span[style*="magiPendingDot"]',
    );
    expect(dots.length).toBe(3);
  });

  it('shows the assistant name above the bubble', () => {
    render(
      <PendingAssistantBubble
        assistantName="Aria"
        assistantAvatar=""
        shouldReduceMotion={false}
      />,
    );
    expect(screen.getByText('Aria')).toBeInTheDocument();
  });

  it('does not attach inline animation styles when reduced motion is requested', () => {
    const { container } = render(
      <PendingAssistantBubble
        assistantName="Magi"
        assistantAvatar=""
        shouldReduceMotion={true}
      />,
    );

    // With reduced motion the dots are still present but render static —
    // no `animation:` inline style so the browser will not animate them.
    const animatedDots = container.querySelectorAll<HTMLSpanElement>(
      'span[style*="magiPendingDot"]',
    );
    expect(animatedDots.length).toBe(0);

    const staticDots = container.querySelectorAll<HTMLSpanElement>(
      'span.rounded-full.bg-muted-foreground\\/70',
    );
    expect(staticDots.length).toBe(3);
  });
});
