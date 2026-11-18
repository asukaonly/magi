const SCENARIOS = 'settings.statistics.llm.requestKindScenarios';

const stagesByScenario: Record<string, Record<string, string>> = {
  [`${SCENARIOS}.generalChat`]: {
    'chat': 'uncategorizedChat',
    'task_agent:chat': 'legacyChat',
    'task_agent:chat_direct': 'directReply',
  },
  [`${SCENARIOS}.supportTasks`]: {
    'auxiliary': 'supportInference',
  },
  [`${SCENARIOS}.toolConversation`]: {
    'function_calling:tools': 'toolDecision',
    'function_calling:chat_tools': 'chatToolDecision',
    'function_calling:worker_tools': 'workerToolDecision',
    'function_calling:final_response': 'finalResponse',
  },
  [`${SCENARIOS}.taskPlanning`]: {
    'task_agent:planner': 'taskDecomposition',
  },
  [`${SCENARIOS}.taskAggregation`]: {
    'task_agent:aggregator': 'multiResultSynthesis',
    'task_agent:failure_status': 'failureStatus',
  },
  [`${SCENARIOS}.exploreTask`]: {
    'task_agent:explore-task': 'execution',
    'task_agent:explore_render': 'resultRendering',
  },
  [`${SCENARIOS}.backgroundTask`]: {
    'task_agent:background_dispatcher': 'backgroundDecision',
    'personal_tasks:watch': 'watchCondition',
  },
  [`${SCENARIOS}.conversationControl`]: {
    'task_agent:chat_interrupt': 'interruptionClassification',
  },
  [`${SCENARIOS}.conversationPolish`]: {
    'task_agent:chat_rhythm': 'rhythmPlanning',
  },
  [`${SCENARIOS}.sessionSummary`]: {
    'memory:context_compact': 'contextCompaction',
    'memory:chat_transcript_summary': 'chatTranscriptSummary',
    'memory:persona_boundary_summary': 'personaBoundarySummary',
  },
  'settings.tabs.memoryKnowledge': {
    'memory:l2_unified_extraction': 'legacyUnifiedExtraction',
    'memory:l2_phase1_extract': 'eventExtraction',
    'memory:l2_phase2_integrate': 'graphIntegration',
    'memory:l2_entity_resolution': 'entityResolution',
    'memory:l2_contradiction_hint': 'contradictionHint',
    'memory:l2_entity_reconcile': 'entityReconcile',
    'memory:l2_self_report_review': 'selfReportReview',
    'memory:l2_experience_seed_selection': 'experienceSelection',
  },
  'settings.tabs.memoryReflection': {
    'memory:l3_temporal_summary': 'temporalSummary',
    'memory:l3_thematic_topic_summary': 'thematicTopicSummary',
    'memory:l3_temporal_summary_prose': 'temporalProse',
    'memory:l3_temporal_summary_structure': 'temporalReview',
    'memory:l3_temporal_summary_repair': 'temporalRepair',
    'memory:l3_thematic_topic_summary_prose': 'topicProse',
    'memory:l3_thematic_topic_summary_structure': 'topicStructure',
    'memory:l3_episodic_summary_prose': 'episodeProse',
    'memory:l3_episodic_summary_structure': 'episodeStructure',
    'memory:l3_experience_review': 'experienceReview',
  },
  'settings.tabs.memorySkills': {
    'l4_strategy_extraction': 'strategyExtraction',
    'memory:l4_strategy_extraction': 'strategyExtraction',
  },
  [`${SCENARIOS}.hybridRetrieval`]: {
    'memory:hybrid_retrieval_intent': 'intentRefinement',
    'memory:hybrid_query_expansion': 'queryExpansion',
    'memory:hybrid_manifest_selector': 'manifestSelection',
    'memory:grounding_filter': 'groundingFilter',
    'memory:assertion_relevance': 'assertionRelevance',
  },
  'settings.tabs.personality': {
    'personality:interaction_analysis': 'interactionAnalysis',
    'personality:bootstrap_opening': 'bootstrapOpening',
    'personality:bootstrap_dialogue': 'bootstrapDialogue',
    'personality:journal_reflection': 'journalReflection',
    'personality:generation': 'personalityGeneration',
    'personality:intent_resolution': 'personaIntent',
    'personality:reference_query_planning': 'referenceSearch',
    'personality:reference_identity_verification': 'referenceIdentity',
    'personality:reference_dossier': 'referenceProfile',
    'outreach:compose': 'outreachMessage',
  },
  [`${SCENARIOS}.configurationTest`]: {
    'config:provider_test': 'providerConnectivity',
  },
  [`${SCENARIOS}.evaluationTool`]: {
    'eval:memory_answering': 'memoryAnswering',
    'eval:llm_judge': 'answerReview',
  },
  [`${SCENARIOS}.multimodalGeneration`]: {
    'image_generation': 'imageGeneration',
    'tts': 'speechGeneration',
  },
  [`${SCENARIOS}.embeddingModel`]: {
    'embedding': 'embedding',
  },
  'settings.tabs.memoryWorkbench': {
    'memory:shared_post_turn_understanding': 'postTurnAttention',
  },
  'timeline.title': {
    'timeline_diary_narrative': 'timelineDiary',
  },
};

const labelsByKind = new Map<string, { scenario: string; stage: string }>();
for (const [scenario, stages] of Object.entries(stagesByScenario)) {
  for (const [kind, stage] of Object.entries(stages)) {
    labelsByKind.set(kind, { scenario, stage: `settings.statistics.llm.requestKindStages.${stage}` });
  }
}

const memoryTabsByLayer = new Map([
  ['memory:l0', 'settings.tabs.memoryWorkbench'],
  ['memory:l1', 'settings.tabs.memoryEvents'],
  ['memory:l2', 'settings.tabs.memoryKnowledge'],
  ['memory:l3', 'settings.tabs.memoryReflection'],
  ['memory:l4', 'settings.tabs.memorySkills'],
]);

export function getUsageScenarioLabels(kind = '') {
  const known = labelsByKind.get(kind);
  if (known) return known;
  const [prefix] = kind.split('_', 1);
  return {
    scenario: memoryTabsByLayer.get(prefix) ?? (kind.startsWith('memory:') ? 'settings.tabs.memory' : `${SCENARIOS}.other`),
    stage: 'settings.statistics.llm.requestKindStages.uncategorized',
  };
}
