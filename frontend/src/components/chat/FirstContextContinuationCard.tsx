import { MessageCircleQuestion, RefreshCw, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

interface FirstContextContinuationCardProps {
  mode: "offer" | "question";
  question?: string;
  onContinue: () => void;
  onDismiss: () => void;
  onChangeQuestion?: () => void;
}

export function FirstContextContinuationCard({
  mode,
  question,
  onContinue,
  onDismiss,
  onChangeQuestion,
}: FirstContextContinuationCardProps): JSX.Element {
  const { t } = useTranslation("app");
  if (mode === "offer") {
    return (
      <div
        className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/15 bg-primary/[0.045] px-4 py-3"
        data-testid="first-context-continuation-offer"
      >
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
            <MessageCircleQuestion className="h-4 w-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-medium text-foreground">
              {t("chat.firstContextContinuation.title")}
            </p>
            <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
              {t("chat.firstContextContinuation.body")}
            </p>
          </div>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <Button
            type="button"
            size="sm"
            className="h-8 rounded-full px-3 text-xs"
            onClick={onContinue}
          >
            {t("chat.firstContextContinuation.continue")}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 rounded-full px-3 text-xs text-muted-foreground"
            onClick={onDismiss}
          >
            {t("chat.firstContextContinuation.startChat")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      className="mb-3 rounded-xl border border-primary/15 bg-primary/[0.045] px-4 py-3"
      data-testid="first-context-continuation-question"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-medium text-primary">
            {t("chat.firstContextContinuation.optional")}
          </p>
          <p className="mt-1 text-sm font-medium leading-6 text-foreground">
            {question}
          </p>
          <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
            {t("chat.firstContextContinuation.inputHint")}
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0 rounded-full text-muted-foreground"
          aria-label={t("chat.firstContextContinuation.dismiss")}
          title={t("chat.firstContextContinuation.dismiss")}
          onClick={onDismiss}
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </Button>
      </div>
      {onChangeQuestion ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="mt-1 h-7 rounded-full px-2 text-xs text-muted-foreground"
          onClick={onChangeQuestion}
        >
          <RefreshCw className="mr-1.5 h-3 w-3" aria-hidden="true" />
          {t("chat.firstContextContinuation.changeQuestion")}
        </Button>
      ) : null}
    </div>
  );
}
