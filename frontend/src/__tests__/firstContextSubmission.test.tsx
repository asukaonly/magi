import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { messagesApi } from "../api/modules/messages";
import {
  DEFAULT_FIRST_CONTEXT_PROGRESS,
  type FirstContextProgress,
} from "../components/onboarding/onboardingProgress";
import { useFirstContextSubmission } from "../components/onboarding/useFirstContextSubmission";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

function harness(progress: FirstContextProgress, waitForRuntimeReady: () => Promise<any>) {
  const progressRef = { current: progress };
  const updateProgress = vi.fn(
    (
      update:
        | Partial<FirstContextProgress>
        | ((current: FirstContextProgress) => FirstContextProgress),
    ) => {
      progressRef.current =
        typeof update === "function"
          ? update(progressRef.current)
          : { ...progressRef.current, ...update };
      return progressRef.current;
    },
  );
  const finishOnboarding = vi.fn().mockResolvedValue(false);
  const hook = renderHook(() =>
    useFirstContextSubmission({
      progress: progressRef.current,
      readProgress: () => progressRef.current,
      updateProgress,
      finishOnboarding,
      waitForRuntimeReady,
    }),
  );
  return { ...hook, progressRef, updateProgress, finishOnboarding };
}

describe("first context submission ownership", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("rejects route, question, and draft changes while readiness is pending", async () => {
    const readiness = deferred<any>();
    const progress: FirstContextProgress = {
      ...DEFAULT_FIRST_CONTEXT_PROGRESS,
      route: "question",
      draft: "original answer",
    };
    const { result, progressRef, updateProgress } = harness(
      progress,
      () => readiness.promise,
    );

    let submission!: Promise<void>;
    act(() => {
      submission = result.current.submit();
    });
    await waitFor(() => expect(result.current.locked).toBe(true));

    act(() => {
      result.current.changeRoute("activity");
      result.current.changeQuestion();
      result.current.changeDraft("mutated answer");
    });
    expect(updateProgress).not.toHaveBeenCalled();
    expect(progressRef.current).toEqual(progress);

    await act(async () => {
      readiness.resolve({ runtime_ready: false });
      await submission;
    });
    expect(result.current.locked).toBe(false);
  });

  it("ignores a late readiness result after unmount", async () => {
    const readiness = deferred<any>();
    const progress: FirstContextProgress = {
      ...DEFAULT_FIRST_CONTEXT_PROGRESS,
      route: "question",
      draft: "answer",
    };
    const { result, unmount, updateProgress, finishOnboarding } = harness(
      progress,
      () => readiness.promise,
    );

    let submission!: Promise<void>;
    act(() => {
      submission = result.current.submit();
    });
    unmount();
    await act(async () => {
      readiness.resolve({ runtime_ready: true });
      await submission;
    });

    expect(updateProgress).not.toHaveBeenCalled();
    expect(finishOnboarding).not.toHaveBeenCalled();
  });

  it("keeps an accepted answer locked when completion fails and retries without resending", async () => {
    const sendSpy = vi.spyOn(messagesApi, "sendMessage").mockResolvedValue({
      success: true,
      message: "accepted",
      data: {
        message_id: "message-1",
        user_id: "local_user",
        session_id: "session-1",
        turn_id: "turn-1",
        message_length: 15,
        timestamp: 1,
      },
    });
    const progress: FirstContextProgress = {
      ...DEFAULT_FIRST_CONTEXT_PROGRESS,
      route: "question",
      draft: "accepted answer",
      sessionCreationKey: "creation-1",
      sessionId: "session-1",
      turnId: "turn-1",
    };
    const {
      result,
      progressRef,
      updateProgress,
      finishOnboarding,
      rerender,
    } = harness(progress, async () => ({ runtime_ready: true }));

    await act(async () => {
      await result.current.submit();
    });
    rerender();
    expect(progressRef.current.submitted).toBe(true);
    expect(sendSpy).toHaveBeenCalledTimes(1);
    expect(finishOnboarding).toHaveBeenCalledTimes(1);

    const writesAfterAcceptance = updateProgress.mock.calls.length;
    act(() => {
      result.current.changeRoute("activity");
      result.current.changeQuestion();
      result.current.changeDraft("replacement answer");
    });
    expect(updateProgress).toHaveBeenCalledTimes(writesAfterAcceptance);
    expect(progressRef.current.draft).toBe("accepted answer");

    await act(async () => {
      await result.current.submit();
    });
    expect(sendSpy).toHaveBeenCalledTimes(1);
    expect(finishOnboarding).toHaveBeenCalledTimes(2);
  });

  it("retries an uncertain send with the same turn id", async () => {
    const sendSpy = vi
      .spyOn(messagesApi, "sendMessage")
      .mockRejectedValueOnce(new Error("response lost"))
      .mockResolvedValueOnce({
        success: true,
        message: "accepted",
        data: {
          message_id: "message-2",
          user_id: "local_user",
          session_id: "session-2",
          turn_id: "turn-server",
          message_length: 16,
          timestamp: 1,
        },
      });
    const progress: FirstContextProgress = {
      ...DEFAULT_FIRST_CONTEXT_PROGRESS,
      route: "question",
      draft: "uncertain answer",
      sessionCreationKey: "creation-2",
      sessionId: "session-2",
    };
    const { result, progressRef } = harness(
      progress,
      async () => ({ runtime_ready: true }),
    );

    await act(async () => {
      await result.current.submit();
    });
    expect(progressRef.current.sendUncertain).toBe(true);
    const firstTurnId = sendSpy.mock.calls[0][0].client_turn_id;

    await act(async () => {
      await result.current.submit();
    });
    expect(sendSpy).toHaveBeenCalledTimes(2);
    expect(sendSpy.mock.calls[1][0].client_turn_id).toBe(firstTurnId);
    expect(progressRef.current.submitted).toBe(true);
  });
});
