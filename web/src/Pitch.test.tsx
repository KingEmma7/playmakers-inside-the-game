import { render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Pitch from "./Pitch";
import fixture from "./fixtures/seed7-events.json";
import type { MatchEvent } from "./stream";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it.each([undefined, "H09"])("keeps the ball clear and spotlights only the followed player (%s)", (favourite) => {
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  let frame: FrameRequestCallback = () => {};
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { frame = callback; return 1; });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  const players: { shirt: string; alpha: number }[] = [];
  const balls: { radius: number; alpha: number; fill: string; stroke: string }[] = [];
  const ctx = {
    globalAlpha: 1, fillStyle: "", strokeStyle: "", lineWidth: 0,
    fillRect: vi.fn(), strokeRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(),
    stroke: vi.fn(), fill: vi.fn(), save: vi.fn(), restore: vi.fn(), setLineDash: vi.fn(),
    ellipse: vi.fn(), roundRect: vi.fn(), measureText: () => ({ width: 90 }),
    arc(_x: number, _y: number, radius: number) {
      if (radius === 12) balls.push({ radius, alpha: this.globalAlpha, fill: this.fillStyle, stroke: this.strokeStyle });
    },
    fillText(text: string) {
      if (/^\d+$/.test(text)) players.push({ shirt: text, alpha: this.globalAlpha });
    },
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as unknown as CanvasRenderingContext2D);
  render(<Pitch events={fixture.slice(0, 2) as unknown as MatchEvent[]} running favourite={favourite} involvement="Okafor" />);
  frame(16);
  expect(players).toHaveLength(22);
  expect(players.filter((p) => p.alpha === 1)).toHaveLength(favourite ? 1 : 22);
  if (favourite) expect(players.find((p) => p.alpha === 1)?.shirt).toBe("9");
  expect(balls).toEqual([{ radius: 12, alpha: 1, fill: "#FFFFFF", stroke: "#1D1D1F" }]);
});
