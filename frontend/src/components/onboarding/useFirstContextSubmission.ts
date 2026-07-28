import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { FIRST_CONTEXT_QUESTION_IDS } from "@/domain/chat/first-context";

import {
  continueFirstContextWithoutConfirmation,
  submitFirstContextStory,
  waitForRuntimeReadyAfterOnboarding,
  type FirstContextCompletionOptions,
  type FirstContextProgressUpdate,
  type FirstContextSubmissionDependencies,
  type RuntimeReadySnapshot,
} from "./firstContextSubmissionFlow";
import type { FirstContextProgress } from "./onboardingProgress";

export type {
  FirstContextCompletionOptions,
  FirstContextProgressUpdate,
  RuntimeReadySnapshot,
} from "./firstContextSubmissionFlow";

interface UseFirstContextSubmissionOptions {
  progress: FirstContextProgress;
  readProgress: () => FirstContextProgress;
  updateProgress: (
    update: FirstContextProgressUpdate,
  ) => FirstContextProgress;
  finishOnboarding: (
    options: FirstContextCompletionOptions,
  ) => Promise<boolean>;
  waitForRuntimeReady?: () => Promise<RuntimeReadySnapshot | null>;
}

export interface UseFirstContextSubmissionResult {
  submitting: boolean;
  error: string | null;
  locked: boolean;
  submitted: boolean;
  changeRoute: (route: FirstContextProgress["route"]) => void;
  changeQuestion: () => void;
  changeDraft: (draft: string) => void;
  submit: () => Promise<void>;
  continueWithoutConfirmation: () => Promise<void>;
}

export function useFirstContextSubmission({
  progress,
  readProgress,
  updateProgress,
  finishOnboarding,
  waitForRuntimeReady = waitForRuntimeReadyAfterOnboarding,
}: UseFirstContextSubmissionOptions): UseFirstContextSubmissionResult {
  const { t } = useTranslation("onboarding");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(false);
  const inFlightRef = useRef(false);
  const ownerTokenRef = useRef(0);
  const dependenciesRef = useRef({
    finishOnboarding,
    readProgress,
    t,
    updateProgress,
    waitForRuntimeReady,
  });
  dependenciesRef.current = {
    finishOnboarding,
    readProgress,
    t,
    updateProgress,
    waitForRuntimeReady,
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      inFlightRef.current = false;
      ownerTokenRef.current += 1;
    };
  }, []);

  const isOwner = useCallback(
    (ownerToken: number): boolean =>
      mountedRef.current && ownerTokenRef.current === ownerToken,
    [],
  );

  const beginSubmission = useCallback((): number | null => {
    if (inFlightRef.current) return null;
    inFlightRef.current = true;
    const ownerToken = ownerTokenRef.current + 1;
    ownerTokenRef.current = ownerToken;
    setSubmitting(true);
    setError(null);
    return ownerToken;
  }, []);

  const endSubmission = useCallback(
    (ownerToken: number): void => {
      if (!isOwner(ownerToken)) return;
      inFlightRef.current = false;
      setSubmitting(false);
    },
    [isOwner],
  );

  const changeRoute = useCallback(
    (route: FirstContextProgress["route"]): void => {
      if (inFlightRef.current) return;
      const current = dependenciesRef.current.readProgress();
      if (current.submitted || current.sendUncertain) return;
      setError(null);
      dependenciesRef.current.updateProgress({ route });
    },
    [],
  );

  const changeQuestion = useCallback((): void => {
    if (inFlightRef.current) return;
    const current = dependenciesRef.current.readProgress();
    if (current.submitted || current.sendUncertain) return;
    setError(null);
    dependenciesRef.current.updateProgress((currentProgress) => {
      const unseenAlternatives = FIRST_CONTEXT_QUESTION_IDS.filter(
        (questionId) =>
          questionId !== currentProgress.questionId &&
          !currentProgress.seenQuestionIds.includes(questionId),
      );
      const startsNewCycle = unseenAlternatives.length === 0;
      const alternatives = startsNewCycle
        ? FIRST_CONTEXT_QUESTION_IDS.filter(
            (questionId) => questionId !== currentProgress.questionId,
          )
        : unseenAlternatives;
      const questionId =
        alternatives[Math.floor(Math.random() * alternatives.length)] ??
        currentProgress.questionId;
      return {
        ...currentProgress,
        questionId,
        seenQuestionIds: startsNewCycle
          ? [currentProgress.questionId, questionId]
          : [...currentProgress.seenQuestionIds, questionId],
        turnId: null,
        messageId: null,
      };
    });
  }, []);

  const changeDraft = useCallback((draft: string): void => {
    if (inFlightRef.current) return;
    const current = dependenciesRef.current.readProgress();
    if (current.submitted || current.sendUncertain) return;
    setError(null);
    dependenciesRef.current.updateProgress({
      draft,
      turnId: null,
      messageId: null,
    });
  }, []);

  const createSubmissionDependencies = useCallback(
    (ownerToken: number): FirstContextSubmissionDependencies => ({
      readProgress: () => dependenciesRef.current.readProgress(),
      updateProgress: (update) =>
        dependenciesRef.current.updateProgress(update),
      finishOnboarding: (options) =>
        dependenciesRef.current.finishOnboarding(options),
      waitForRuntimeReady: () =>
        dependenciesRef.current.waitForRuntimeReady(),
      translate: (key) => dependenciesRef.current.t(key),
      isOwner: () => isOwner(ownerToken),
      setError: (message) => {
        if (isOwner(ownerToken)) setError(message);
      },
    }),
    [isOwner],
  );

  const submit = useCallback(async (): Promise<void> => {
    const current = dependenciesRef.current.readProgress();
    const message = current.draft.trim();
    if (!message) {
      setError(dependenciesRef.current.t("firstContext.story.errors.empty"));
      return;
    }

    const ownerToken = beginSubmission();
    if (ownerToken === null) return;
    try {
      await submitFirstContextStory(
        message,
        createSubmissionDependencies(ownerToken),
      );
    } catch {
      if (isOwner(ownerToken)) {
        setError(
          dependenciesRef.current.t("firstContext.story.errors.sendFailed"),
        );
      }
    } finally {
      endSubmission(ownerToken);
    }
  }, [
    beginSubmission,
    createSubmissionDependencies,
    endSubmission,
    isOwner,
  ]);

  const continueWithoutConfirmation =
    useCallback(async (): Promise<void> => {
      const current = dependenciesRef.current.readProgress();
      if (!current.sendUncertain) return;

      const ownerToken = beginSubmission();
      if (ownerToken === null) return;
      try {
        await continueFirstContextWithoutConfirmation(
          current,
          createSubmissionDependencies(ownerToken),
        );
      } finally {
        endSubmission(ownerToken);
      }
    }, [beginSubmission, createSubmissionDependencies, endSubmission]);

  return {
    submitting,
    error,
    locked:
      submitting ||
      inFlightRef.current ||
      progress.submitted ||
      progress.sendUncertain,
    submitted: progress.submitted,
    changeRoute,
    changeQuestion,
    changeDraft,
    submit,
    continueWithoutConfirmation,
  };
}
