import { memo, useEffect, useRef } from "react";

const vertexShaderSource = `
  attribute vec2 position;

  void main() {
    gl_Position = vec4(position, 0.0, 1.0);
  }
`;

const fragmentShaderSource = `
  precision highp float;

  uniform vec2 resolution;
  uniform vec2 pointer;
  uniform float progress;
  uniform float time;

  float hash(float n) {
    return fract(sin(n) * 43758.5453123);
  }

  float hash2(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }

  float ringField(vec2 p, float angle, float radius) {
    vec2 q = vec2(
      cos(angle) * p.x - sin(angle) * p.y,
      sin(angle) * p.x + cos(angle) * p.y
    );
    float r = length(q);
    float a = atan(q.y, q.x);
    float wobble = sin(a * 7.0 + time * 0.32) * 0.024 +
      sin(a * 19.0 - time * 0.19) * 0.011;
    return abs(r - radius - wobble);
  }

  void main() {
    vec2 uv = gl_FragCoord.xy / resolution;
    vec2 p = (gl_FragCoord.xy * 2.0 - resolution) / min(resolution.x, resolution.y);
    vec2 mouse = (pointer * 2.0 - 1.0) * vec2(resolution.x / resolution.y, 1.0);

    float rot = time * 0.08 + progress * 1.8;
    float radius = mix(0.58, 0.76, smoothstep(0.12, 0.88, progress));
    float field = ringField(p, rot, radius);
    float body = smoothstep(0.19, 0.025, field);
    float inner = smoothstep(0.08, 0.018, field);

    float angle = atan(p.y, p.x);
    float segment = floor((angle + 3.14159265) / 6.2831853 * 96.0);
    float radial = floor(length(p) * 34.0);
    float fracture = hash2(vec2(segment, radial));
    float crackA = abs(fract((angle + 3.14159265) / 6.2831853 * 96.0) - 0.5);
    float crackR = abs(fract(length(p) * 34.0 + fracture * 0.8) - 0.5);
    float crack = (1.0 - smoothstep(0.0, 0.055, crackA)) +
      (1.0 - smoothstep(0.0, 0.035, crackR));
    crack *= body;

    float pointerHit = 1.0 - smoothstep(0.02, 0.58, distance(p, mouse));
    float lift = pointerHit * body * 0.38;
    float spark = pow(max(0.0, 1.0 - field * 14.0), 2.0) * (0.24 + fracture * 0.6);
    vec3 stone = vec3(0.34, 0.31, 0.26) * (0.68 + fracture * 0.24);
    vec3 ember = vec3(1.0, 0.22, 0.02);
    vec3 gold = vec3(1.0, 0.68, 0.20);

    float shellShade = body * (0.42 + 0.58 * smoothstep(-0.7, 0.85, p.y + p.x * 0.28));
    vec3 color = (stone + lift * vec3(0.34, 0.10, 0.02)) * shellShade;
    color += ember * crack * 0.35;
    color += gold * inner * spark * 0.62;
    color += ember * pointerHit * body * 0.26;
    color += vec3(1.0, 0.36, 0.05) * pow(max(0.0, 1.0 - field * 26.0), 3.0) * 0.18;

    float vignette = smoothstep(1.34, 0.24, length(p));
    color *= 0.44 + vignette * 0.72;
    color += vec3(1.0, 0.22, 0.02) * smoothstep(0.9, 0.0, abs(length(p) - radius)) * 0.035;
    float alpha = clamp(body * 0.66 + crack * 0.18 + inner * spark * 0.34, 0.0, 0.88);

    gl_FragColor = vec4(color, alpha);
  }
`;

const createShader = (
  gl: WebGLRenderingContext,
  source: string,
  type: number
): WebGLShader | undefined => {
  const shader = gl.createShader(type);

  if (!shader) return undefined;

  gl.shaderSource(shader, source);
  gl.compileShader(shader);

  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return undefined;
  }

  return shader;
};

const createProgram = (gl: WebGLRenderingContext): WebGLProgram | undefined => {
  const vertexShader = createShader(gl, vertexShaderSource, gl.VERTEX_SHADER);
  const fragmentShader = createShader(
    gl,
    fragmentShaderSource,
    gl.FRAGMENT_SHADER
  );

  if (!vertexShader || !fragmentShader) return undefined;

  const program = gl.createProgram();

  if (!program) return undefined;

  gl.attachShader(program, vertexShader);
  gl.attachShader(program, fragmentShader);
  gl.linkProgram(program);
  gl.deleteShader(vertexShader);
  gl.deleteShader(fragmentShader);

  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    gl.deleteProgram(program);
    return undefined;
  }

  return program;
};

type FractureRingCanvasProps = {
  progress: number;
};

const FractureRingCanvas = ({
  progress,
}: FractureRingCanvasProps): React.ReactElement => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const progressRef = useRef(progress);

  useEffect(() => {
    progressRef.current = progress;
  }, [progress]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const gl = canvas?.getContext("webgl", {
      alpha: true,
      antialias: false,
      powerPreference: "high-performance",
    });

    if (!canvas || !gl) {
      return () => {
        // No canvas context was created.
      };
    }

    const program = createProgram(gl);

    if (!program) {
      return () => {
        // Shader compilation failed before resources were allocated.
      };
    }

    const positionLocation = gl.getAttribLocation(program, "position");
    const positionBuffer = gl.createBuffer();

    if (!positionBuffer || positionLocation < 0) {
      gl.deleteProgram(program);
      return () => {
        // Buffer allocation failed after program creation.
      };
    }

    const resolutionLocation = gl.getUniformLocation(program, "resolution");
    const pointerLocation = gl.getUniformLocation(program, "pointer");
    const progressLocation = gl.getUniformLocation(program, "progress");
    const timeLocation = gl.getUniformLocation(program, "time");
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const pointer = { x: 0.5, y: 0.5 };
    let animationId = 0;
    let start = performance.now();

    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, -1, -1, 1, 1, 1]),
      gl.STATIC_DRAW
    );
    gl.enableVertexAttribArray(positionLocation);
    gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);

    const resize = (): void => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const width = Math.floor(window.innerWidth * dpr);
      const height = Math.floor(window.innerHeight * dpr);

      canvas.width = width;
      canvas.height = height;
      gl.viewport(0, 0, width, height);
      gl.uniform2f(resolutionLocation, width, height);
    };

    const move = (event: PointerEvent): void => {
      pointer.x = event.clientX / window.innerWidth;
      pointer.y = 1 - event.clientY / window.innerHeight;
    };

    const render = (): void => {
      const elapsed = reduce ? 0 : (performance.now() - start) * 0.001;

      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform1f(timeLocation, elapsed);
      gl.uniform1f(progressLocation, progressRef.current);
      gl.uniform2f(pointerLocation, pointer.x, pointer.y);
      gl.drawArrays(gl.TRIANGLES, 0, 6);

      animationId = window.requestAnimationFrame(render);
    };

    resize();
    start = performance.now();
    render();
    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("resize", resize, { passive: true });

    return () => {
      if (animationId) window.cancelAnimationFrame(animationId);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("resize", resize);
      gl.deleteBuffer(positionBuffer);
      gl.deleteProgram(program);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="fracture-ring-canvas"
    />
  );
};

export default memo(FractureRingCanvas);
