import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import LoadingState from "./LoadingState";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});
const advance = (ms: number) => act(() => vi.advanceTimersByTime(ms));

it("never shows when the first event arrives before 250 ms", () => {
  const { rerender } = render(<LoadingState waiting />);
  advance(200);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  rerender(<LoadingState waiting={false} />);
  advance(1000);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("shows after 250 ms, holds for 400 ms, then fades and unmounts", () => {
  const { rerender } = render(<LoadingState waiting />);
  advance(249);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  advance(1);
  const card = screen.getByRole("status");
  expect(card).toHaveTextContent("Getting the match ready…");
  expect(card).toHaveAttribute("aria-live", "polite");
  advance(100);
  rerender(<LoadingState waiting={false} />);
  advance(299);
  expect(card.parentElement).not.toHaveClass("is-fading");
  advance(1);
  expect(card.parentElement).toHaveClass("is-fading");
  advance(179);
  expect(card).toBeInTheDocument();
  advance(1);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("delays reconnection and uses the reconnecting copy", () => {
  const { rerender } = render(<LoadingState waiting={false} />);
  rerender(<LoadingState waiting reconnecting />);
  advance(249);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  advance(1);
  expect(screen.getByRole("status")).toHaveTextContent("Reconnecting to the match…");
});

it("cancels a pending fade when waiting resumes", () => {
  const { rerender } = render(<LoadingState waiting />);
  advance(650);
  rerender(<LoadingState waiting={false} />);
  advance(0);
  expect(screen.getByRole("status").parentElement).toHaveClass("is-fading");
  rerender(<LoadingState waiting reconnecting />);
  advance(0);
  expect(screen.getByRole("status").parentElement).not.toHaveClass("is-fading");
  advance(1000);
  expect(screen.getByRole("status")).toHaveTextContent("Reconnecting to the match…");
});

it("cleans up both delay and fade timers on unmount", () => {
  const first = render(<LoadingState waiting />);
  first.unmount();
  expect(vi.getTimerCount()).toBe(0);
  const second = render(<LoadingState waiting />);
  advance(250);
  second.rerender(<LoadingState waiting={false} />);
  advance(400);
  second.unmount();
  expect(vi.getTimerCount()).toBe(0);
});
