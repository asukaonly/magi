import type { TFunction } from 'i18next';

const ROUND_LABEL_PATTERN = /^Round\s+(\d+)$/i;
const ITERATION_LABEL_PATTERN = /^Iteration\s+(\d+)$/i;

export const formatTraceStatus = (status: string, t: TFunction<'app'>): string => {
  if (status === 'completed') return t('chat.trace.statusCompleted');
  if (status === 'failed') return t('chat.trace.statusError');
  if (status === 'blocked') return t('chat.trace.statusBlocked');
  if (status === 'suspended') return t('chat.trace.statusSuspended');
  if (status === 'cancelled') return t('chat.trace.statusCancelled');
  if (status === 'interrupted') return t('chat.trace.statusInterrupted');
  if (status === 'merged') return t('chat.trace.statusMerged');
  return t('chat.trace.statusRunning');
};

export const formatTraceMode = (mode: string, t: TFunction<'app'>): string => {
  if (mode === 'orchestration') return t('chat.trace.modeOrchestration');
  if (mode === 'direct_llm') return t('chat.trace.modeDirectLlm');
  if (mode === 'function_calling') return t('chat.trace.modeFunctionCalling');
  if (mode === 'agent_loop') return t('chat.trace.modeAgentLoop');
  return mode || '--';
};

export const formatTraceKind = (kind: string, t: TFunction<'app'>): string => {
  const mapping: Record<string, string> = {
    root: 'chat.trace.kindRoot',
    planning: 'chat.trace.kindPlanning',
    parallel_group: 'chat.trace.kindParallelGroup',
    worker: 'chat.trace.kindWorker',
    tool: 'chat.trace.kindTool',
    tool_call: 'chat.trace.kindTool',
    iteration: 'chat.trace.kindIteration',
    llm: 'chat.trace.kindLlm',
    llm_call: 'chat.trace.kindLlm',
    skill: 'chat.trace.kindSkill',
    skill_call: 'chat.trace.kindSkill',
    response: 'chat.trace.kindResponse',
    rhythm: 'chat.trace.kindRhythm',
    dispatch: 'chat.trace.kindDispatch',
    attempt: 'chat.trace.kindAttempt',
    step: 'chat.trace.kindStep',
    validation: 'chat.trace.kindValidation',
    repair: 'chat.trace.kindRepair',
    reasoning: 'chat.trace.kindReasoning',
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
  if (label === 'Main LLM call') return t('chat.trace.node.coreModelProcessing');
  if (label === 'Response emission') return t('chat.trace.node.responseEmission');
  if (label === 'Response rhythm processing') return t('chat.trace.node.responseRhythmProcessing');
  if (label === 'Task orchestration') return t('chat.trace.node.taskOrchestration');
  if (label === 'Tool chain') return t('chat.trace.node.callTrace');
  if (label === 'Model decision') return t('chat.trace.node.modelDecision');
  if (label === 'Validation') return t('chat.trace.node.validation');
  if (label === 'Completion check') return t('chat.trace.node.completionCheck');
  if (label === 'Repairing completion requirements') return t('chat.trace.node.repair');
  if (label === 'Reasoning depth adjusted') return t('chat.trace.node.reasoningAdjusted');

  const roundMatch = ROUND_LABEL_PATTERN.exec(label);
  if (roundMatch) {
    return t('chat.trace.node.roundLabel', { count: Number(roundMatch[1]) || 0 });
  }
  const iterMatch = ITERATION_LABEL_PATTERN.exec(label);
  if (iterMatch) {
    return t('chat.trace.node.roundLabel', { count: Number(iterMatch[1]) || 0 });
  }
  return label;
};
