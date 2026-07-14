import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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
    expect(primaryAction).toHaveClass('h-12', 'min-w-[9.5rem]', 'rounded-xl', 'bg-[#7b4d33]');
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
        steps={['欢迎', '配置模型', '选择人格', '首次上下文', '完成']}
        current={1}
      />,
    );

    const activeStep = screen.getByText('配置模型').closest('li');
    expect(activeStep).toHaveAttribute('aria-current', 'step');
    expect(activeStep).toHaveClass('bg-accent/70');
    expect(screen.getByText('03')).toBeInTheDocument();
    expect(document.querySelector('.rounded-full')).not.toBeInTheDocument();
  });
});
