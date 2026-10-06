/**
 * Custom drawing overlay for the chart.
 *
 * Horizontal levels (hline / entry / stop / target) are rendered as native
 * lightweight-charts price lines by ChartPanel; every other object is drawn
 * on a synchronized canvas overlay: trend lines, rays, rectangles/zones,
 * vertical lines and text labels. Supports hit-testing, endpoint handles,
 * dragging and live previews.
 */
import type { IChartApi, ISeriesApi } from "lightweight-charts";
import type { Drawing } from "@/lib/types";

export interface HitResult {
  id: string;
  handle: 0 | 1 | "body" | null;
}

export class DrawLayer {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private ro: ResizeObserver;

  constructor(
    private container: HTMLElement,
    private chart: IChartApi,
    private series: ISeriesApi<"Candlestick">
  ) {
    this.canvas = document.createElement("canvas");
    this.canvas.style.position = "absolute";
    this.canvas.style.inset = "0";
    this.canvas.style.pointerEvents = "none";
    this.canvas.style.zIndex = "5";
    container.appendChild(this.canvas);
    this.ctx = this.canvas.getContext("2d")!;
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(container);
    this.resize();
  }

  destroy() {
    this.ro.disconnect();
    this.canvas.remove();
  }

  private resize() {
    const dpr = window.devicePixelRatio || 1;
    const { width, height } = this.container.getBoundingClientRect();
    this.canvas.width = Math.round(width * dpr);
    this.canvas.height = Math.round(height * dpr);
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  invalidate() {
    this.resize();
  }

  /* ---------------- coordinate mapping ---------------- */

  private x(time: number): number | null {
    const c = this.chart.timeScale().timeToCoordinate(time as never);
    return c === null ? null : c;
  }

  private y(price: number): number | null {
    const c = this.series.priceToCoordinate(price);
    return c === null ? null : c;
  }

  timeFromX(px: number): number | null {
    const t = this.chart.timeScale().coordinateToTime(px as never);
    return t === null ? null : (t as number);
  }

  priceFromY(py: number): number | null {
    const p = this.series.coordinateToPrice(py as never);
    return p === null ? null : (p as number);
  }

  /* ---------------- rendering ---------------- */

  render(drawings: Drawing[], draft: Drawing | null, selectedId: string | null) {
    const { width, height } = this.container.getBoundingClientRect();
    this.ctx.clearRect(0, 0, width, height);
    for (const d of drawings) {
      if (d.hidden) continue;
      this.drawOne(d, d.id === selectedId);
    }
    if (draft) this.drawOne(draft, true);
  }

  private drawOne(d: Drawing, selected: boolean) {
    const ctx = this.ctx;
    ctx.save();
    ctx.globalAlpha = d.opacity;
    ctx.strokeStyle = d.color;
    ctx.fillStyle = d.color;
    ctx.lineWidth = d.width;
    ctx.setLineDash(d.type === "ray" ? [6, 4] : []);

    const p0 = d.points[0];
    const p1 = d.points[1];

    switch (d.type) {
      case "trend":
      case "ray": {
        if (!p0 || !p1) break;
        const x0 = this.x(p0.time); const y0 = this.y(p0.price);
        const x1 = this.x(p1.time); const y1 = this.y(p1.price);
        if (x0 === null || y0 === null || x1 === null || y1 === null) break;
        let ex = x1; let ey = y1;
        if (d.type === "ray" && x1 !== x0) {
          // extend through p1 to the chart edge
          const dir = x1 > x0 ? 1 : -1;
          const edge = dir > 0 ? this.canvas.clientWidth : 0;
          const t = (edge - x0) / (x1 - x0);
          if (t > 1) { ex = edge; ey = y0 + (y1 - y0) * t; }
        }
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(ex, ey);
        ctx.stroke();
        break;
      }
      case "rect": {
        if (!p0 || !p1) break;
        const x0 = this.x(p0.time); const y0 = this.y(p0.price);
        const x1 = this.x(p1.time); const y1 = this.y(p1.price);
        if (x0 === null || y0 === null || x1 === null || y1 === null) break;
        const rx = Math.min(x0, x1); const ry = Math.min(y0, y1);
        const rw = Math.abs(x1 - x0); const rh = Math.abs(y1 - y0);
        ctx.globalAlpha = d.opacity * 0.14;
        ctx.fillRect(rx, ry, rw, rh);
        ctx.globalAlpha = d.opacity * 0.75;
        ctx.strokeRect(rx, ry, rw, rh);
        break;
      }
      case "vline": {
        if (!p0) break;
        const x0 = this.x(p0.time);
        if (x0 === null) break;
        ctx.beginPath();
        ctx.moveTo(x0, 0);
        ctx.lineTo(x0, this.canvas.clientHeight);
        ctx.stroke();
        break;
      }
      case "text": {
        if (!p0) break;
        const x0 = this.x(p0.time); const y0 = this.y(p0.price);
        if (x0 === null || y0 === null) break;
        const label = d.label || "note";
        ctx.font = "10px 'JetBrains Mono', monospace";
        const w = ctx.measureText(label).width + 10;
        ctx.globalAlpha = d.opacity * 0.85;
        ctx.fillStyle = "#0e131b";
        ctx.strokeStyle = d.color;
        ctx.beginPath();
        ctx.roundRect(x0, y0 - 8, w, 16, 3);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = d.color;
        ctx.fillText(label, x0 + 5, y0 + 3);
        break;
      }
      default:
        break; // hline-like rendered natively as price lines
    }

    // selection handles
    if (selected) {
      ctx.setLineDash([]);
      for (const idx of [0, 1]) {
        const p = d.points[idx];
        if (!p) continue;
        if (idx === 1 && (d.type === "hline" || d.type === "vline" || d.type === "text" || d.points.length === 1)) continue;
        const px = d.type === "hline" ? 14 : this.x(p.time);
        const py = this.y(p.price);
        if (px === null || py === null) continue;
        ctx.fillStyle = "#0e131b";
        ctx.strokeStyle = d.color;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.rect(px - 3.5, py - 3.5, 7, 7);
        ctx.fill();
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  /* ---------------- hit testing ---------------- */

  hitTest(px: number, py: number, drawings: Drawing[]): HitResult | null {
    // endpoints first (only unlocked objects are interactive)
    for (let i = drawings.length - 1; i >= 0; i--) {
      const d = drawings[i];
      if (d.hidden || d.locked) continue;
      for (let h = 0; h < d.points.length; h++) {
        const p = d.points[h];
        const hx = d.type === "hline" ? 14 : this.x(p.time);
        const hy = this.y(p.price);
        if (hx === null || hy === null) continue;
        if (Math.abs(px - hx) <= 7 && Math.abs(py - hy) <= 7) {
          return { id: d.id ?? "", handle: h as 0 | 1 };
        }
      }
    }
    // bodies
    for (let i = drawings.length - 1; i >= 0; i--) {
      const d = drawings[i];
      if (d.hidden || d.locked) continue;
      if (d.type === "hline" || d.type === "entry" || d.type === "stop" || d.type === "target") {
        const hy = this.y(d.points[0]?.price ?? NaN);
        if (hy !== null && Math.abs(py - hy) <= 5) return { id: d.id ?? "", handle: null };
      } else if (d.type === "vline") {
        const hx = this.x(d.points[0]?.time ?? NaN);
        if (hx !== null && Math.abs(px - hx) <= 5) return { id: d.id ?? "", handle: "body" };
      } else if (d.type === "text") {
        const hx = this.x(d.points[0]?.time ?? NaN);
        const hy = this.y(d.points[0]?.price ?? NaN);
        if (hx !== null && hy !== null && px >= hx && px <= hx + 90 && Math.abs(py - hy) <= 10) {
          return { id: d.id ?? "", handle: "body" };
        }
      } else if (d.type === "rect" && d.points.length === 2) {
        const x0 = this.x(d.points[0].time); const x1 = this.x(d.points[1].time);
        const y0 = this.y(d.points[0].price); const y1 = this.y(d.points[1].price);
        if (x0 !== null && x1 !== null && y0 !== null && y1 !== null) {
          const inX = px >= Math.min(x0, x1) && px <= Math.max(x0, x1);
          const inY = py >= Math.min(y0, y1) && py <= Math.max(y0, y1);
          if (inX && inY) return { id: d.id ?? "", handle: "body" };
        }
      } else if ((d.type === "trend" || d.type === "ray") && d.points.length === 2) {
        const x0 = this.x(d.points[0].time); const y0 = this.y(d.points[0].price);
        const x1 = this.x(d.points[1].time); const y1 = this.y(d.points[1].price);
        if (x0 !== null && y0 !== null && x1 !== null && y1 !== null) {
          if (distToSegment(px, py, x0, y0, x1, y1) <= 6) return { id: d.id ?? "", handle: "body" };
        }
      }
    }
    return null;
  }
}

function distToSegment(px: number, py: number, x0: number, y0: number, x1: number, y1: number): number {
  const dx = x1 - x0;
  const dy = y1 - y0;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(px - x0, py - y0);
  let t = ((px - x0) * dx + (py - y0) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x0 + t * dx), py - (y0 + t * dy));
}
