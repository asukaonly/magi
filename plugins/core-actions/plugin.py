"""Official built-in actions plugin."""
from __future__ import annotations

from magi.plugins import ActionExecutionContext, ActionSpec, BaseAction, ExtensionFieldSpec, Plugin


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
        return [SendEmailAction()]
