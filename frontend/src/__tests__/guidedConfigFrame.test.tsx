import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import GuidedConfigFrame from '@/components/config-forms/GuidedConfigFrame';

describe('GuidedConfigFrame', () => {
  it('constrains height to viewport and keeps the content pane scrollable', () => {
    const { container } = render(
      <GuidedConfigFrame sidebar={<div>sidebar</div>} footer={<div>footer</div>}>
        <div>content</div>
      </GuidedConfigFrame>
    );

    const root = screen.getByText('content').closest('.rounded-3xl');
    const contentPane = screen.getByText('content').parentElement;
    const footerPane = screen.getByText('footer').parentElement;

    expect(root?.className).toContain('max-h-[calc(100vh-2rem)]');
    expect(container.innerHTML).not.toContain('min-h-[clamp(560px,78vh,760px)]');
    expect(contentPane?.className).toContain('min-h-0');
    expect(contentPane?.className).toContain('overflow-y-auto');
    expect(footerPane?.className).toContain('shrink-0');
  });

  it('supports a stable viewport-filling shell without stretching the footer', () => {
    render(
      <GuidedConfigFrame className="h-[clamp(620px,82vh,840px)]" footer={<div>footer</div>}>
        <div>content</div>
      </GuidedConfigFrame>
    );

    const root = screen.getByText('content').closest('.rounded-3xl');
    const footerPane = screen.getByText('footer').parentElement;

    expect(root?.className).toContain('h-[clamp(620px,82vh,840px)]');
    expect(footerPane?.className).toContain('shrink-0');
  });
});
