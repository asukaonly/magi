import type { TFunction } from 'i18next';

const ROUND_LABEL_PATTERN = /^Round\s+(\d+)$/i;

export const formatTraceStatus = (status: string, t: TFunction<'app'>): string => {
  if (status === 'completed') return t('chat.trace.statusCompleted');
  if (status === 'failed') return t('chat.trace.statusError');
  return t('chat.trace.statusRunning');
};

export const formatTraceMode = (mode: string, t: TFunction<'app'>): string => {
  if (mode === 'orchestration') return t('chat.trace.modeOrchestration');
  if (mode === 'direct_llm') return t('chat.trace.modeDirectLlm');
  if (mode === 'function_calling') return t('chat.trace.modeFunctionCalling');
  return mode || '--';
};

export const formatTraceKind = (kind: string, t: TFunction<'app'>): string => {
  const mapping: Record<string, string> = {
    root: 'chat.trace.kindRoot',
    planning: 'chat.trace.kindPlanning',
    parallel_group: 'chat.trace.kindParallelGroup',
    worker: 'chat.trace.kindWorker',
    tool: 'chat.trace.kindTool',
    iteration: 'chat.trace.kindIteration',
    intent: 'chat.trace.kindIntent',
    llm: 'chat.trace.kindLlm',
    response: 'chat.trace.kindResponse',
    dispatch: 'chat.trace.kindDispatch',
    attempt: 'chat.trace.kindAttempt',
  };
  const key = mapping[kind];
  return key ? t(key) : kind;
};

export const formatTraceLabel = (
  label: string,
  kind: string,
  t: TFunction<'app'>,
): string => {
  if (kind === 'root') return t('chat.trace.node.callTrace');
  if (label === 'Intent resolution') return t('chat.trace.node.intentResolution');
  if (label === 'Main LLM call') return t('chat.trace.node.mainLlmCall');
  if (label === 'Response emission') return t('chat.trace.node.responseEmission');
  if (label === 'Task orchestration') return t('chat.trace.node.taskOrchestration');
  if (label === 'Tool chain') return t('chat.trace.node.callTrace');

  const roundMatch = ROUND_LABEL_PATTERN.exec(label);
  if (roundMatch) {
    return t('chat.trace.node.roundLabel', { count: Number(roundMatch[1]) || 0 });
  }
  return label;
};
