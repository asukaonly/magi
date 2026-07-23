import {
  defineChatPageSuite,
} from "@/test/chatPageHarness";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { ChatPage } from "@/pages/Chat";
import { useConversationStore } from "@/stores/conversation-store";
import { normalizeHistoryMessages } from "@/domain/chat/state";
import { messagesApi } from "@/api";

const seedFirstContextConversation = () => {
  useConversationStore.getState().receiveHistory(
    "session-1",
    normalizeHistoryMessages([
      {
        message_id: "first-context-name",
        message_kind: "user_text",
        role: "user",
        content: "明日香",
        timestamp: 1000,
        turn_id: "turn-name",
        kind: "user",
        payload: {
          interaction_kind: "first_context_story",
          first_context: {
            question_id: "preferred_name",
            question_text: "希望 Magi 平时怎么称呼你？昵称就可以。",
          },
        },
      },
      {
        message_id: "first-context-name-reply",
        message_kind: "assistant_final",
        role: "assistant",
        content: "好，明日香。",
        timestamp: 1100,
        turn_id: "turn-name",
        kind: "assistant",
      },
    ]),
  );
};

defineChatPageSuite("ChatPage first-context continuation", () => {
  it("offers one next question and sends the answer through the same chat", async () => {
    window.localStorage.clear();
    seedFirstContextConversation();
    const user = userEvent.setup();

    render(<ChatPage />);

    expect(
      await screen.findByTestId("first-context-continuation-offer"),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: "chat.firstContextContinuation.continue",
      }),
    );

    const question = await screen.findByTestId(
      "first-context-continuation-question",
    );
    expect(question).toHaveTextContent("firstContext.story.questions.");

    const input = screen.getByRole("textbox");
    await user.type(input, "最近一直在看城市散步路线");
    await user.click(screen.getByRole("button", { name: "chat.send" }));

    await waitFor(() => {
      expect(messagesApi.sendMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          session_id: "session-1",
          message: "最近一直在看城市散步路线",
          interaction_kind: "first_context_story",
          first_context: {
            question_id: expect.stringMatching(
              /^(easy_topic|current_interest|repeating_content)$/,
            ),
            question_text: expect.stringContaining(
              "firstContext.story.questions.",
            ),
          },
        }),
      );
    });
    await waitFor(() => {
      expect(input).toHaveValue("");
    });
    const optimisticAnswer = useConversationStore
      .getState()
      .messagesBySession["session-1"]?.find(
        (message) =>
          message.content === "最近一直在看城市散步路线",
      );
    expect(optimisticAnswer?.payload).toEqual({
      interaction_kind: "first_context_story",
      first_context: expect.objectContaining({
        question_id: expect.stringMatching(
          /^(easy_topic|current_interest|repeating_content)$/,
        ),
      }),
    });
  });

  it("keeps a dismissed follow-up hidden after reopening the chat", async () => {
    window.localStorage.clear();
    seedFirstContextConversation();
    const user = userEvent.setup();
    const firstRender = render(<ChatPage />);

    await user.click(
      await screen.findByRole("button", {
        name: "chat.firstContextContinuation.startChat",
      }),
    );
    expect(
      screen.queryByTestId("first-context-continuation-offer"),
    ).not.toBeInTheDocument();

    firstRender.unmount();
    render(<ChatPage />);

    await waitFor(() => {
      expect(
        screen.queryByTestId("first-context-continuation-offer"),
      ).not.toBeInTheDocument();
    });
    expect(
      Object.keys(window.localStorage).some((key) =>
        key.startsWith("magi.first-context-continuation:session-1"),
      ),
    ).toBe(true);
  });
});
