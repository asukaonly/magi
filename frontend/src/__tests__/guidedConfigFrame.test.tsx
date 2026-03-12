import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import GuidedConfigFrame from '@/components/config-forms/GuidedConfigFrame';

describe('GuidedConfigFrame', () => {
  it('constrains height to viewport and keeps the content pane scrollable', () => {
    render(
      <GuidedConfigFrame sidebar={<div>sidebar</div>} footer={<div>footer</div>}>
        <div>content</div>
      </GuidedConfigFrame>
    );

    const root = screen.getByText('content').closest('.rounded-3xl');
    const contentPane = screen.getByText('content').parentElement;

    expect(root?.className).toContain('max-h-[calc(100vh-2rem)]');
    expect(contentPane?.className).toContain('min-h-0');
    expect(contentPane?.className).toContain('overflow-y-auto');
  });
});
