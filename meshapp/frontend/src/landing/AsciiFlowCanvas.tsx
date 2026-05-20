import { memo, useEffect, useRef } from "react";

const ASCII_RAMP = ".,:;irsXA253hMHGS#9B&@";
const CELL_SIZE = 8;
const MAX_DPR = 2;

type AsciiFlowCanvasProps = {
  progress: number;
};

type Particle = {
  brightness: number;
  charOffset: number;
  depth: number;
  speed: number;
  x: number;
  y: number;
};

const clamp = (value: number, min: number, max: number): number =>
  Math.max(min, Math.min(max, value));

const smoothstep = (edge0: number, edge1: number, value: number): number => {
  const t = clamp((value - edge0) / (edge1 - edge0), 0, 1);

  return t * t * (3 - 2 * t);
};

const asciiCharFor = (value: number, offset: number, time: number): string => {
  const drift = (Math.sin(time * 0.003 + offset) + 1) * 0.08;
  const index = Math.floor(
    clamp(value + drift, 0, 1) * (ASCII_RAMP.length - 1)
  );

  return ASCII_RAMP[index];
};

const buildBrightnessGrid = (
  width: number,
  height: number,
  progress: number
): number[][] => {
  const cols = Math.max(1, Math.ceil(width / CELL_SIZE));
  const rows = Math.max(1, Math.ceil(height / CELL_SIZE));
  const minSide = Math.max(1, Math.min(width, height));
  const centerX = width * 0.52;
  const centerY = height * 0.5;
  const radius = 0.58 + smoothstep(0.12, 0.88, progress) * 0.18;

  return Array.from({ length: rows }, (_rowValue, row) =>
    Array.from({ length: cols }, (_colValue, col) => {
      const x = col * CELL_SIZE + CELL_SIZE * 0.5;
      const y = row * CELL_SIZE + CELL_SIZE * 0.5;
      const px = ((x - centerX) * 2) / minSide;
      const py = ((y - centerY) * 2) / minSide;
      const ringAngle = Math.atan2(py, px);
      const ringWobble =
        Math.sin(ringAngle * 7 + progress * 2.4) * 0.026 +
        Math.sin(ringAngle * 19 - progress * 1.7) * 0.012;
      const ringField = Math.abs(Math.hypot(px, py) - radius - ringWobble);
      const ringMask = smoothstep(0.21, 0.035, ringField);
      const shard =
        Math.sin((x - y * 1.72) * 0.018) * 0.5 +
        Math.sin((x * 0.015 + y * 0.006) + ringAngle * 5) * 0.5;
      const lane = smoothstep(-0.18, 0.92, shard);
      const backgroundShard =
        Math.sin((x - y * 1.58) * 0.015) * 0.5 +
        Math.cos((x * 0.006 + y * 0.021) - progress * 4) * 0.5;
      const backgroundLane = smoothstep(0.72, 0.99, backgroundShard) * 0.28;
      const crossCut =
        1 -
        smoothstep(
          0.028,
          0.13,
          Math.abs(Math.sin(ringAngle * 9 + progress * 3.1))
        );

      return clamp(
        backgroundLane + ringMask * (0.44 + lane * 1.08) + crossCut * ringMask * 0.18,
        0,
        1
      );
    })
  );
};

const createParticles = (width: number, height: number): Particle[] => {
  const target = clamp(Math.floor((width * height) / 320), 1600, 4800);

  return Array.from({ length: target }, () => ({
    brightness: 0,
    charOffset: Math.random() * 1000,
    depth: 0.62 + Math.random() * 0.86,
    speed: 0,
    x: Math.random() * width,
    y: Math.random() * height,
  }));
};

const AsciiFlowCanvas = ({
  progress,
}: AsciiFlowCanvasProps): React.ReactElement => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const progressRef = useRef(progress);

  useEffect(() => {
    progressRef.current = progress;
  }, [progress]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d", { alpha: true });

    if (!canvas || !ctx) {
      return () => {
        // No canvas context was created.
      };
    }

    const pointer = { x: 0.72, y: 0.2 };
    const flow = { x: 0.44, y: -0.9 };
    let width = 0;
    let height = 0;
    let dpr = 1;
    let particles: Particle[] = [];
    let brightnessGrid: number[][] = [];
    let animationId = 0;
    let lastGridProgress = -1;

    const refreshGrid = (): void => {
      const nextProgress = Math.round(progressRef.current * 100) / 100;

      if (nextProgress === lastGridProgress && brightnessGrid.length > 0) return;
      lastGridProgress = nextProgress;
      brightnessGrid = buildBrightnessGrid(width, height, progressRef.current);
    };

    const resize = (): void => {
      dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      particles = createParticles(width, height);
      lastGridProgress = -1;
      refreshGrid();
    };

    const move = (event: PointerEvent): void => {
      pointer.x = event.clientX / Math.max(1, width);
      pointer.y = event.clientY / Math.max(1, height);
    };

    const render = (time: number): void => {
      refreshGrid();

      const targetX = pointer.x - 0.5;
      const targetY = pointer.y - 0.5;
      const length = Math.hypot(targetX, targetY) || 1;
      const desiredX = targetX / length;
      const desiredY = targetY / length;

      flow.x += (desiredX - flow.x) * 0.045;
      flow.y += (desiredY - flow.y) * 0.045;

      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#050711";
      ctx.fillRect(0, 0, width, height);
      ctx.globalAlpha = 1;
      ctx.font = "12px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      for (const particle of particles) {
        const col = clamp(Math.floor(particle.x / CELL_SIZE), 0, brightnessGrid[0].length - 1);
        const row = clamp(Math.floor(particle.y / CELL_SIZE), 0, brightnessGrid.length - 1);
        const brightness = brightnessGrid[row][col];
        const speed = 1.05 + brightness * 5.2 + particle.depth * 0.64;

        particle.brightness = brightness;
        particle.speed = speed;
        particle.x += flow.x * speed;
        particle.y += flow.y * speed;

        if (particle.x > width + 72) particle.x = -72;
        if (particle.x < -72) particle.x = width + 72;
        if (particle.y > height + 72) particle.y = -72;
        if (particle.y < -72) particle.y = height + 72;
        if (brightness >= 0.12) {
          const char = asciiCharFor(brightness, particle.charOffset, time);
          const size = 9 + particle.depth * 6.8;
          const alpha = clamp(0.08 + brightness * 1.02, 0, 0.98);

          ctx.font = `${size}px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace`;
          ctx.shadowBlur = 14 + brightness * 24;
          ctx.shadowColor = "rgba(170, 220, 255, 0.95)";
          ctx.fillStyle = "rgb(232, 246, 255)";
          ctx.globalAlpha = alpha;
          ctx.fillText(char, particle.x, particle.y);
          ctx.globalAlpha = alpha * 0.42;
          ctx.shadowBlur = 8;
          ctx.fillText(char, particle.x - flow.x * 14, particle.y - flow.y * 14);
          ctx.globalAlpha = alpha * 0.24;
          ctx.fillText(char, particle.x - flow.x * 28, particle.y - flow.y * 28);
          ctx.globalAlpha = alpha * 0.12;
          ctx.fillText(char, particle.x - flow.x * 42, particle.y - flow.y * 42);
        }
      }

      animationId = window.requestAnimationFrame(render);
    };

    resize();
    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("resize", resize, { passive: true });
    animationId = window.requestAnimationFrame(render);

    return () => {
      if (animationId) window.cancelAnimationFrame(animationId);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="ascii-flow-canvas"
    />
  );
};

export default memo(AsciiFlowCanvas);
