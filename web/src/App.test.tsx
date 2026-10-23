import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./stream", async (original) => ({
  ...await original<typeof import("./stream")>(),
  usePlaymakersStream: () => ({ events: [], cues: [], traces: [], status: "connecting" }),
}));
vi.mock("./Pitch", () => ({ default: () => <div /> }));
afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
  history.replaceState(null, "", "/");
});
it("introduces the crew, hides on About and remembers dismissal for the session", () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ json: async () => ({ live: false }) }));
  const { unmount } = render(<App />);
  expect(screen.getByRole("note")).toHaveTextContent("8 AI and rule-based agents");
  expect(screen.getByLabelText("MATCH SEED")).toHaveValue(382);
  fireEvent.click(screen.getByRole("link", { name: "About" }));
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: "Replay" }));
  fireEvent.click(screen.getByRole("button", { name: "Dismiss introduction" }));
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
  unmount();
  render(<App />);
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
});
