import { useState } from "react";
import { CheckCircle2, Circle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { personasApi } from "../../../api/modules/personas";

export function GenerationStageStatusIcon({
  status,
  shouldReduceMotion,
}: {
  status: string;
  shouldReduceMotion: boolean;
}): JSX.Element {
  if (status === "completed") {
    return (
      <CheckCircle2
        className="h-4 w-4 text-primary"
        aria-hidden="true"
      />
    );
  }
  if (status === "running") {
    return (
      <Loader2
        data-testid="persona-generation-stage-spinner"
        className={cn(
          "h-4 w-4 text-primary",
          !shouldReduceMotion && "animate-spin",
        )}
        aria-hidden="true"
      />
    );
  }
  return (
    <Circle
      className="h-3.5 w-3.5 text-muted-foreground/45"
      aria-hidden="true"
    />
  );
}

export function PreviewAvatar({
  name,
  avatar,
  size = "md",
}: {
  name: string;
  avatar?: string;
  size?: "md" | "lg";
}): JSX.Element {
  const [failed, setFailed] = useState(false);
  const url = avatar ? personasApi.getAvatarUrl(avatar) : "";
  const initial = name.trim().charAt(0).toUpperCase() || "?";
  const boxClass = size === "lg" ? "h-16 w-16" : "h-10 w-10";
  const textClass = size === "lg" ? "text-lg" : "text-sm";

  if (!url || failed) {
    return (
      <div
        className={cn(
          "flex shrink-0 items-center justify-center rounded-full bg-muted font-semibold text-muted-foreground",
          boxClass,
          textClass,
        )}
      >
        {initial}
      </div>
    );
  }
  return (
    <img
      src={url}
      alt=""
      onError={() => setFailed(true)}
      className={cn(
        "shrink-0 rounded-full object-cover",
        boxClass,
      )}
    />
  );
}

export function TypingDots({
  shouldReduceMotion,
  label,
}: {
  shouldReduceMotion: boolean;
  label: string;
}): JSX.Element {
  return (
    <span
      className="flex items-center gap-1.5 py-0.5"
      role="status"
      aria-label={label}
    >
      {[0, 180, 360].map((delay) => (
        <span
          key={delay}
          aria-hidden
          className="block h-1.5 w-1.5 rounded-full bg-muted-foreground/70"
          style={
            shouldReduceMotion
              ? undefined
              : {
                  animation: `magiPendingDot 1.2s ease-in-out ${delay}ms infinite`,
                }
          }
        />
      ))}
    </span>
  );
}
