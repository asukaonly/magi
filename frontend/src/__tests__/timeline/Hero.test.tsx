import { render, screen } from "@testing-library/react";
import type { ImgHTMLAttributes } from "react";
import { describe, it, expect, vi } from "vitest";

import { Hero } from "@/components/timeline/immersive/Hero";

vi.mock("@/components/media/ProtectedImage", () => {
  const ProtectedImage = ({
    eager,
    onProtectedAccessError,
    ...imageProps
  }: ImgHTMLAttributes<HTMLImageElement> & {
    eager?: boolean;
    onProtectedAccessError?: () => void;
  }) => {
    void eager;
    void onProtectedAccessError;
    return <img {...imageProps} />;
  };
  return { ProtectedImage, default: ProtectedImage };
});

describe("Hero", () => {
  it("renders date label, essence prose, and place line", () => {
    render(
      <Hero
        dateLabel="2026 · 5 · 17 · 周日"
        essenceProse="周日。你大部分时间在 localhost 之间游走。"
        placeLine="家 · 楼下咖啡店"
        photoUrl={null}
        fallbackTone="cool"
      />
    );

    expect(screen.getByText("2026 · 5 · 17 · 周日")).toBeInTheDocument();
    expect(
      screen.getByText("周日。你大部分时间在 localhost 之间游走。")
    ).toBeInTheDocument();
    expect(screen.getByText(/家.*楼下咖啡店/)).toBeInTheDocument();
  });

  it("renders an <img> when photoUrl is provided", () => {
    render(
      <Hero
        dateLabel="2026 · 5 · 17"
        essenceProse=""
        photoUrl="/api/timeline/asset/photo-library%3A%2F%2F2026-05-17%2FIMG.HEIC"
        fallbackTone="warm"
      />
    );

    const img = screen.getByRole("img", { hidden: true });
    expect(img).toHaveAttribute(
      "src",
      "/api/timeline/asset/photo-library%3A%2F%2F2026-05-17%2FIMG.HEIC"
    );
  });

  it("omits the place line element when not provided", () => {
    render(
      <Hero
        dateLabel="2026 · 5 · 17"
        essenceProse="x"
        photoUrl={null}
        fallbackTone="neutral"
      />
    );

    expect(screen.queryByText(/家/)).not.toBeInTheDocument();
  });

  it("applies different classes for different fallback tones", () => {
    const { container, rerender } = render(
      <Hero
        dateLabel="d"
        essenceProse="e"
        photoUrl={null}
        fallbackTone="warm"
      />
    );
    const warmClass = (container.firstElementChild as HTMLElement).className;

    rerender(
      <Hero
        dateLabel="d"
        essenceProse="e"
        photoUrl={null}
        fallbackTone="tense"
      />
    );
    const tenseClass = (container.firstElementChild as HTMLElement).className;
    expect(tenseClass).not.toBe(warmClass);
  });
});
