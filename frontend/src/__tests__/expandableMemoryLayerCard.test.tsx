import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '@/i18n';
import { ExpandableMemoryLayerCard } from '@/components/settings/ExpandableMemoryLayerCard';

beforeEach(async () => { await i18n.changeLanguage('en'); });
afterEach(async () => { await i18n.changeLanguage('en'); });

describe('memory layer expansion', () => {
  it('exposes a named, keyboard-operable control and matching content state', async () => {
    const user = userEvent.setup();
    function Card() {
      const [expanded, setExpanded] = useState(false);
      return <ExpandableMemoryLayerCard layerKey="l1" label="L1" description="Daily memory" checked expanded={expanded} onToggle={vi.fn()} onExpand={setExpanded}><input aria-label="Retention" /></ExpandableMemoryLayerCard>;
    }
    render(<Card />);
    const control = screen.getByRole('button', { name: 'Expand L1 settings' });
    const content = document.getElementById(control.getAttribute('aria-controls')!);
    expect(content).toHaveAttribute('hidden');
    expect(control).toHaveAttribute('aria-expanded', 'false');
    await user.tab();
    expect(screen.getByRole('switch', { name: 'L1' })).toHaveFocus();
    await user.tab();
    expect(control).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(control).toHaveAccessibleName('Collapse L1 settings');
    expect(control).toHaveAttribute('aria-expanded', 'true');
    expect(content).toBeVisible();
    expect(screen.getByRole('textbox', { name: 'Retention' })).toBeVisible();
    await user.keyboard(' ');
    expect(control).toHaveAttribute('aria-expanded', 'false');
    expect(content).not.toBeVisible();
    expect(screen.queryByRole('textbox', { name: 'Retention' })).not.toBeInTheDocument();
  });

  it.each([
    { name: 'disabled layer', checked: true, disabled: true, children: <span>Details</span> },
    { name: 'inactive layer', checked: false, disabled: false, children: <span>Details</span> },
    { name: 'no content', checked: true, disabled: false, children: undefined },
  ])('prevents expansion for $name', async ({ checked, disabled, children }) => {
    const onExpand = vi.fn();
    const user = userEvent.setup();
    render(<ExpandableMemoryLayerCard layerKey="l1" label="L1" description="Daily memory" checked={checked} disabled={disabled} expanded={false} onToggle={vi.fn()} onExpand={onExpand}>{children}</ExpandableMemoryLayerCard>);
    const control = screen.getByRole('button', { name: 'Expand L1 settings' });
    expect(control).toBeDisabled();
    await user.click(control);
    expect(onExpand).not.toHaveBeenCalled();
  });

  it('translates the control name using the current language', async () => {
    await i18n.changeLanguage('zh-CN');
    render(<ExpandableMemoryLayerCard layerKey="l1" label="情景记忆" description="日常经历" checked expanded onToggle={vi.fn()} onExpand={vi.fn()}><span>内容</span></ExpandableMemoryLayerCard>);
    expect(screen.getByRole('button', { name: '收起情景记忆设置' })).toHaveAttribute('aria-expanded', 'true');
  });
});
