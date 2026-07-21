import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import GuidedConfigFrame from '@/components/config-forms/GuidedConfigFrame';
import StepIndicator from '@/components/onboarding/StepIndicator';
import WelcomeScreen from '@/components/onboarding/WelcomeScreen';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe('onboarding visual controls', () => {
  it('uses one restrained primary action and a text-led language switch', () => {
    const onContinue = vi.fn();
    const onLanguageChange = vi.fn();

    render(
      <WelcomeScreen
        language="zh"
        onLanguageChange={onLanguageChange}
        onContinue={onContinue}
      />,
    );

    const primaryAction = screen.getByRole('button', { name: 'welcome.getStarted' });
    expect(primaryAction).toHaveClass(
      'h-12',
      'min-w-[9.5rem]',
      'rounded-xl',
      'bg-primary',
      'text-primary-foreground',
    );
    expect(primaryAction).not.toHaveClass('bg-foreground');
    expect(primaryAction).not.toHaveClass('rounded-[14px]');
    expect(document.querySelector('img')?.parentElement).toHaveClass('mb-8');

    const chinese = screen.getByRole('button', { name: '中文' });
    const english = screen.getByRole('button', { name: 'EN' });
    expect(chinese).toHaveAttribute('aria-pressed', 'true');
    expect(english).toHaveAttribute('aria-pressed', 'false');
    expect(chinese).toHaveClass('h-11');

    fireEvent.click(primaryAction);
    fireEvent.click(english);
    expect(onContinue).toHaveBeenCalledTimes(1);
    expect(onLanguageChange).toHaveBeenCalledWith('en');
  });

  it('presents progress as a quiet ordered list instead of numbered circles', () => {
    render(
      <StepIndicator
        steps={['配置模型', '选择人格', '首次上下文', '完成']}
        current={0}
      />,
    );

    const activeStep = screen.getByText('配置模型').closest('li');
    expect(activeStep).toHaveAttribute('aria-current', 'step');
    expect(activeStep).toHaveClass('min-w-[8.25rem]', 'lg:min-w-0');
    expect(activeStep?.querySelector('[aria-hidden="true"]')).toHaveClass('h-px', 'lg:w-px');
    expect(activeStep).not.toHaveClass('rounded-xl', 'bg-accent/90');
    expect(screen.getByText('01')).toBeInTheDocument();
    expect(screen.getByText('04')).toBeInTheDocument();
    expect(screen.queryByText('欢迎')).not.toBeInTheDocument();
    expect(document.querySelector('.rounded-full')).not.toBeInTheDocument();
  });

  it('uses the full window as the onboarding workspace', () => {
    render(
      <GuidedConfigFrame sidebar={<span>步骤</span>} footer={<button>继续</button>}>
        <span>内容</span>
      </GuidedConfigFrame>,
    );

    const frame = screen.getByTestId('guided-config-frame');
    expect(frame).toHaveClass('h-full', 'w-full', 'bg-muted/25');
    expect(frame).not.toHaveClass('rounded-3xl', 'border', 'shadow-lg');

    const sidebar = screen.getByText('步骤').closest('aside');
    expect(sidebar).toHaveClass('bg-muted/70', 'overflow-x-auto', 'lg:overflow-y-auto');
    expect(screen.getByTestId('guided-config-content')).toHaveClass('overflow-hidden');
    expect(screen.getByRole('contentinfo')).toHaveClass('bg-background');
    expect(screen.getByRole('contentinfo').className).not.toContain('shadow-[');
  });
});
