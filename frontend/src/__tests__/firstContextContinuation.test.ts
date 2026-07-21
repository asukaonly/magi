import { describe, expect, it } from "vitest";
import {
  answeredFirstContextQuestionIds,
  canOfferFirstContextContinuation,
  chooseAlternativeFirstContextQuestion,
  chooseNextFirstContextQuestion,
} from "@/domain/chat/first-context";
import type { ChatTimelineMessage } from "@/domain/chat/state";

const firstContextAnswer = (
  questionId: string,
  timestamp: number,
): ChatTimelineMessage => ({
  id: `user-${timestamp}`,
  role: "user",
  kind: "user",
  messageKind: "user_text",
  content: "answer",
  timestamp,
  payload: {
    interaction_kind: "first_context_story",
    first_context: {
      question_id: questionId,
      question_text: "question",
    },
  },
});

const assistantReply = (timestamp: number): ChatTimelineMessage => ({
  id: `assistant-${timestamp}`,
  role: "assistant",
  kind: "assistant",
  messageKind: "assistant_final",
  content: "reply",
  timestamp,
});

describe("first-context continuation", () => {
  it("keeps the preferred name first, then asks about interests and daily life", () => {
    expect(chooseNextFirstContextQuestion("session-1", [])).toBe(
      "preferred_name",
    );
    const interest = chooseNextFirstContextQuestion("session-1", [
      "preferred_name",
    ]);
    expect(["easy_topic", "current_interest", "repeating_content"]).toContain(
      interest,
    );
    const life = chooseNextFirstContextQuestion("session-1", [
      "preferred_name",
      interest!,
    ]);
    expect(["recent_feeling", "personal_time", "reluctant_routine"]).toContain(
      life,
    );
  });

  it("does not repeat an answered question when changing the prompt", () => {
    const next = chooseAlternativeFirstContextQuestion(
      "current_interest",
      "session-1",
      ["preferred_name", "easy_topic"],
    );
    expect(next).not.toBe("current_interest");
    expect(next).not.toBe("easy_topic");
  });

  it("starts a new cycle after every question in the current group was seen", () => {
    const next = chooseAlternativeFirstContextQuestion(
      "current_interest",
      "session-1",
      ["preferred_name"],
      ["easy_topic", "current_interest", "repeating_content"],
    );

    expect(["easy_topic", "repeating_content"]).toContain(next);
    expect(next).not.toBe("current_interest");
  });

  it("offers another question only after the assistant finishes replying", () => {
    const answer = firstContextAnswer("preferred_name", 1);
    expect(canOfferFirstContextContinuation([answer], false)).toBe(false);
    expect(
      canOfferFirstContextContinuation([answer, assistantReply(2)], false),
    ).toBe(true);
    expect(
      canOfferFirstContextContinuation([answer, assistantReply(2)], true),
    ).toBe(false);
  });

  it("stops after three answers or when ordinary chat has already continued", () => {
    const twoTurns = [
      firstContextAnswer("preferred_name", 1),
      assistantReply(2),
      {
        ...firstContextAnswer("current_interest", 3),
        id: "interest",
      },
      assistantReply(4),
    ];
    expect(answeredFirstContextQuestionIds(twoTurns)).toEqual([
      "preferred_name",
      "current_interest",
    ]);
    expect(
      canOfferFirstContextContinuation([
        ...twoTurns,
        {
          id: "ordinary",
          role: "user",
          kind: "user",
          content: "ordinary chat",
          timestamp: 5,
        },
        assistantReply(6),
      ], false),
    ).toBe(false);
    expect(
      canOfferFirstContextContinuation([
        ...twoTurns,
        firstContextAnswer("recent_feeling", 5),
        assistantReply(6),
      ], false),
    ).toBe(false);
  });
});
