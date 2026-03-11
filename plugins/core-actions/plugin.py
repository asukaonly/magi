"""Official built-in actions plugin."""
from __future__ import annotations

from magi.plugins import ActionExecutionContext, ActionSpec, BaseAction, ExtensionFieldSpec, Plugin


class NotifyUserAction(BaseAction):
    def build_spec(self) -> ActionSpec:
        return ActionSpec(
            action_id="notify-user",
            display_name="Notify User",
            description="Send an in-app notification to the user.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Notification title"},
                    "message": {"type": "string", "description": "Notification body"},
                },
                "required": ["message"],
            },
            fields=[
                ExtensionFieldSpec(
                    key="notifications.default_level",
                    type="select",
                    label="Default Notification Level",
                    description="Default severity used for user notifications.",
                    default="info",
                    options=[
                        {"label": "Info", "value": "info"},
                        {"label": "Warning", "value": "warning"},
                        {"label": "Critical", "value": "critical"},
                    ],
                    section="notifications",
                    surface="actions",
                    order=10,
                )
            ],
            tool_adapter_name="notify-user",
            tool_adapter_description="Send an in-app notification to the current user.",
        )

    async def execute(
        self,
        parameters: dict[str, object],
        context: ActionExecutionContext,
    ) -> dict[str, object]:
        return {
            "status": "sent",
            "channel": "in_app",
            "delivery": "simulated",
            "title": str(parameters.get("title") or "Notification"),
            "message": str(parameters.get("message") or ""),
            "user_id": context.user_id,
        }


class SendEmailAction(BaseAction):
    def build_spec(self) -> ActionSpec:
        return ActionSpec(
            action_id="send-email",
            display_name="Send Email",
            description="Send an outbound email through the configured action provider.",
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body"},
                },
                "required": ["to", "subject", "body"],
            },
            fields=[
                ExtensionFieldSpec(
                    key="email.default_sender",
                    type="input",
                    label="Default Sender",
                    description="Default sender address for email actions.",
                    default="",
                    section="email",
                    surface="actions",
                    order=10,
                ),
                ExtensionFieldSpec(
                    key="email.provider_mode",
                    type="select",
                    label="Delivery Mode",
                    description="How email delivery is performed.",
                    default="simulated",
                    options=[
                        {"label": "Simulated", "value": "simulated"},
                    ],
                    section="email",
                    surface="actions",
                    order=20,
                ),
            ],
            tool_adapter_name="send-email",
            tool_adapter_description="Send an outbound email message.",
        )

    async def execute(
        self,
        parameters: dict[str, object],
        context: ActionExecutionContext,
    ) -> dict[str, object]:
        return {
            "status": "queued",
            "delivery": "simulated",
            "to": str(parameters.get("to") or ""),
            "subject": str(parameters.get("subject") or ""),
            "body": str(parameters.get("body") or ""),
            "requested_by": context.user_id,
        }


class CoreActionsPlugin(Plugin):
    def get_actions(self):
        return [NotifyUserAction(), SendEmailAction()]
