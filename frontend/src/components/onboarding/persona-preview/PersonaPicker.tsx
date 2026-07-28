import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import type { RailItem } from "./personaPreviewModel";
import { PreviewAvatar } from "./PersonaPreviewPrimitives";

interface PersonaPickerProps {
  items: RailItem[];
  activeSeed: string | null;
  disabled: boolean;
  shouldReduceMotion: boolean;
  onSelect: (seedSlug: string) => void;
  onEnter: (item: RailItem, mode: "chat" | "profile") => void;
  onCreate: () => void;
}

export function PersonaPicker({
  items,
  activeSeed,
  disabled,
  shouldReduceMotion,
  onSelect,
  onEnter,
  onCreate,
}: PersonaPickerProps): JSX.Element {
  const { t } = useTranslation("onboarding");

  return (
    <motion.div
      key="persona-picker"
      className="min-h-0 flex-1 overflow-y-auto"
      initial={
        shouldReduceMotion ? false : { opacity: 0, x: -16 }
      }
      animate={{ opacity: 1, x: 0 }}
      transition={{
        duration: shouldReduceMotion ? 0 : 0.24,
        ease: [0.22, 1, 0.36, 1],
      }}
    >
      <div className="grid grid-cols-2 gap-3 p-1 sm:grid-cols-3 xl:grid-cols-4">
        {items.map((item) => {
          const selected = activeSeed === item.slug;
          return (
            <div
              key={item.slug}
              className={cn(
                "group relative flex flex-col items-center gap-3 rounded-xl px-4 py-6 text-center shadow-[inset_0_0_0_1px_hsl(var(--border)/0.58)] transition-[background-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:bg-card hover:shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.35),0_10px_28px_-24px_hsl(var(--foreground)/0.3)] motion-reduce:transform-none motion-reduce:transition-none",
                selected
                  ? "bg-card shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.38)]"
                  : "bg-transparent",
              )}
            >
              <button
                type="button"
                data-testid={`persona-pick-${item.slug}`}
                aria-pressed={selected}
                aria-label={item.name}
                disabled={disabled}
                onClick={() => onSelect(item.slug)}
                className="absolute inset-0 rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
              />
              {selected ? (
                <span
                  aria-hidden="true"
                  className="absolute right-3 top-3 z-10 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground"
                >
                  <Check className="h-3 w-3" />
                </span>
              ) : null}
              <span className="pointer-events-none flex min-w-0 flex-col items-center gap-3">
                <PreviewAvatar
                  name={item.name}
                  avatar={item.avatar}
                  size="lg"
                />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-foreground">
                    {item.name}
                  </span>
                </span>
              </span>
              <span className="relative flex h-9 w-full items-center justify-center">
                <span className="pointer-events-none absolute inset-0 flex items-start justify-center text-xs leading-5 text-muted-foreground transition-opacity duration-200 line-clamp-2 group-hover:opacity-0 group-focus-within:opacity-0 motion-reduce:transition-none">
                  {item.description}
                </span>
                <span className="absolute inset-0 z-10 flex items-center justify-center gap-1.5 opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100 motion-reduce:transition-none">
                  <button
                    type="button"
                    data-testid={`persona-chat-${item.slug}`}
                    disabled={disabled}
                    onClick={() => onEnter(item, "chat")}
                    className="rounded-md bg-muted px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                  >
                    {t("personaPreview.chatAction")}
                  </button>
                  <button
                    type="button"
                    data-testid={`persona-profile-${item.slug}`}
                    disabled={disabled}
                    onClick={() => onEnter(item, "profile")}
                    className="rounded-md bg-muted px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  >
                    {t("personaPreview.profileAction")}
                  </button>
                </span>
              </span>
            </div>
          );
        })}
        <button
          type="button"
          data-testid="persona-create-custom"
          aria-pressed={false}
          disabled={disabled}
          onClick={onCreate}
          className="group flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border px-4 py-6 text-center text-muted-foreground transition-colors duration-200 hover:border-primary/45 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20 motion-reduce:transition-none"
        >
          <span className="flex h-16 w-16 items-center justify-center rounded-full bg-muted/70 text-2xl shadow-[inset_0_0_0_1px_hsl(var(--border)/0.65)] transition-colors group-hover:text-foreground">
            +
          </span>
          <span className="text-sm font-semibold">
            {t("personaPreview.createCustom")}
          </span>
        </button>
      </div>
    </motion.div>
  );
}
