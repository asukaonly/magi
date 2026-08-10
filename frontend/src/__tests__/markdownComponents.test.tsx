import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ReactMarkdown from 'react-markdown';
import { describe, expect, it, vi } from 'vitest';

import { createMarkdownComponents } from '@/components/ui/markdown-components';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, values?: { host?: string }) => {
      if (key === 'markdown.remoteImage.blocked') {
        return `Remote image from ${values?.host || 'external'}`;
      }
      if (key === 'markdown.remoteImage.load') {
        return 'Load image';
      }
      return key;
    },
  }),
}));

function renderMarkdown(markdown: string) {
  return render(
    <ReactMarkdown components={createMarkdownComponents()}>
      {markdown}
    </ReactMarkdown>,
  );
}

describe('shared Markdown image privacy', () => {
  it('does not load a remote image until the user chooses that image', async () => {
    const user = userEvent.setup();
    renderMarkdown('![tracking pixel](https://images.example.test/pixel.png?user=42)');

    expect(screen.queryByRole('img', { name: 'tracking pixel' })).not.toBeInTheDocument();
    expect(screen.getByText('Remote image from images.example.test')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Load image' }));

    const image = screen.getByRole('img', { name: 'tracking pixel' });
    expect(image).toHaveAttribute(
      'src',
      'https://images.example.test/pixel.png?user=42',
    );
    expect(image).toHaveAttribute('referrerpolicy', 'no-referrer');
  });

  it('blocks protocol-relative remote images too', () => {
    renderMarkdown('![remote](//cdn.example.test/image.png)');

    expect(screen.queryByRole('img', { name: 'remote' })).not.toBeInTheDocument();
    expect(screen.getByText('Remote image from cdn.example.test')).toBeInTheDocument();
  });

  it('keeps local image rendering available', () => {
    renderMarkdown('![local](/assets/history-image.png)');

    expect(screen.getByRole('img', { name: 'local' })).toHaveAttribute(
      'src',
      '/assets/history-image.png',
    );

  });
});
