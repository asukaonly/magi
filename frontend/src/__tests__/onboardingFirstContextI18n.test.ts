import { describe, expect, it } from "vitest";

import enOnboarding from "@/i18n/locales/en/onboarding.json";
import zhCnOnboarding from "@/i18n/locales/zh-CN/onboarding.json";
import enApp from "@/i18n/locales/en/app.json";
import zhCnApp from "@/i18n/locales/zh-CN/app.json";

const QUESTION_IDS = [
  "preferred_name",
  "easy_topic",
  "current_interest",
  "repeating_content",
  "recent_feeling",
  "personal_time",
  "reluctant_routine",
] as const;

const REQUIRED_PATHS = [
  "kicker",
  "title",
  "body",
  "routes.back",
  "routes.optional",
  "routes.question.title",
  "routes.question.body",
  "routes.question.meta",
  "routes.activity.title",
  "routes.activity.body",
  "routes.activity.meta",
  "routes.note",
  "story.kicker",
  "story.title",
  "story.body",
  "story.badge",
  "story.questionLabel",
  "story.changeQuestion",
  "story.shortHint",
  "story.inputHint",
  "story.inputLabel",
  "story.contextNote",
  "story.privacyNote",
  "story.submit",
  "story.submitting",
  "story.retryEntering",
  "story.continueWithoutConfirmation",
  "story.errors.empty",
  "story.errors.runtimeNotReady",
  "story.errors.sessionFailed",
  "story.errors.sendFailed",
  "story.errors.confirmationUnavailable",
  "story.errors.finishFailed",
  "activity.title",
  "activity.body",
] as const;

const CONTINUATION_PATHS = [
  "title",
  "body",
  "continue",
  "startChat",
  "optional",
  "inputHint",
  "dismiss",
  "changeQuestion",
  "attachmentsUnsupported",
] as const;

function readPath(value: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((current, segment) => {
    if (!current || typeof current !== "object") {
      return undefined;
    }
    return (current as Record<string, unknown>)[segment];
  }, value);
}

function leafPaths(value: unknown, prefix = ""): string[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return [prefix];
  }
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    leafPaths(child, prefix ? `${prefix}.${key}` : key),
  );
}

describe("first-context onboarding copy", () => {
  it("keeps every route and recovery message translated in both locales", () => {
    for (const resource of [zhCnOnboarding, enOnboarding]) {
      for (const path of REQUIRED_PATHS) {
        expect(readPath(resource.firstContext, path), path).toEqual(
          expect.any(String),
        );
        expect(
          String(readPath(resource.firstContext, path)).trim(),
          path,
        ).not.toBe("");
      }
    }
  });

  it("keeps the optional in-chat continuation translated in both locales", () => {
    for (const resource of [zhCnApp, enApp]) {
      for (const path of CONTINUATION_PATHS) {
        const value = readPath(
          resource.chat.firstContextContinuation,
          path,
        );
        expect(value, path).toEqual(expect.any(String));
        expect(String(value).trim(), path).not.toBe("");
      }
    }
  });

  it("keeps Markdown import copy aligned in both locales", () => {
    expect(leafPaths(enOnboarding.firstContext.history).sort()).toEqual(
      leafPaths(zhCnOnboarding.firstContext.history).sort(),
    );
    expect(
      leafPaths(enApp.memory.sourcesPage.historyImports).sort(),
    ).toEqual(
      leafPaths(zhCnApp.memory.sourcesPage.historyImports).sort(),
    );
  });

  it("does not present generic Markdown as a chat importer", () => {
    for (const resource of [zhCnOnboarding, enOnboarding]) {
      expect(resource.firstContext.history.picker.scenarios).not.toHaveProperty(
        "conversation",
      );
      expect(resource.firstContext.history).not.toHaveProperty("identity");
      expect(resource.firstContext.history.preview.kind).toEqual({
        document: expect.any(String),
      });
    }
  });

  it("keeps personal and everyday question ids aligned", () => {
    expect(Object.keys(zhCnOnboarding.firstContext.story.questions)).toEqual(
      QUESTION_IDS,
    );
    expect(Object.keys(enOnboarding.firstContext.story.questions)).toEqual(
      QUESTION_IDS,
    );
    for (const questionId of QUESTION_IDS) {
      expect(
        zhCnOnboarding.firstContext.story.questions[questionId].trim(),
      ).not.toBe("");
      expect(
        enOnboarding.firstContext.story.questions[questionId].trim(),
      ).not.toBe("");
      expect(
        zhCnOnboarding.firstContext.story.placeholders[questionId].trim(),
      ).not.toBe("");
      expect(
        enOnboarding.firstContext.story.placeholders[questionId].trim(),
      ).not.toBe("");
    }
  });

  it("starts with low-effort personal questions", () => {
    expect(QUESTION_IDS.slice(0, 3)).toEqual([
      "preferred_name",
      "easy_topic",
      "current_interest",
    ]);
    expect(
      zhCnOnboarding.firstContext.story.questions.preferred_name,
    ).toContain("称呼");
    expect(enOnboarding.firstContext.story.questions.preferred_name).toContain(
      "call",
    );
  });

  it("uses neutral instructional placeholders for every question", () => {
    for (const questionId of QUESTION_IDS) {
      const zhPlaceholder =
        zhCnOnboarding.firstContext.story.placeholders[questionId];
      const enPlaceholder =
        enOnboarding.firstContext.story.placeholders[questionId];

      expect(zhPlaceholder).toMatch(/^请输入/);
      expect(zhPlaceholder).not.toContain("比如");
      expect(enPlaceholder).toMatch(/^Enter /);
      expect(enPlaceholder).not.toMatch(/for example/i);
    }
  });

  it("only promises local storage for the chat record", () => {
    expect(zhCnOnboarding.firstContext.story.privacyNote).toContain(
      "聊天记录保存在本机",
    );
    expect(enOnboarding.firstContext.story.privacyNote).toContain(
      "The chat record is stored on this device",
    );
  });
});
