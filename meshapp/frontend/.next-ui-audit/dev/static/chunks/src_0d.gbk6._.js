(globalThis["TURBOPACK"] || (globalThis["TURBOPACK"] = [])).push([typeof document === "object" ? document.currentScript : undefined,
"[project]/src/landing/AsciiFlowCanvas.tsx [app-client] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "default",
    ()=>__TURBOPACK__default__export__
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/next@16.2.6_@playwright+test@1.60.0_react-dom@19.2.6_react@19.2.6__react@19.2.6/node_modules/next/dist/compiled/react/jsx-dev-runtime.js [app-client] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/next@16.2.6_@playwright+test@1.60.0_react-dom@19.2.6_react@19.2.6__react@19.2.6/node_modules/next/dist/compiled/react/index.js [app-client] (ecmascript)");
;
var _s = __turbopack_context__.k.signature();
;
const ASCII_RAMP = ".,:;irsXA253hMHGS#9B&@";
const CELL_SIZE = 8;
const MAX_DPR = 2;
const clamp = (value, min, max)=>Math.max(min, Math.min(max, value));
const smoothstep = (edge0, edge1, value)=>{
    const t = clamp((value - edge0) / (edge1 - edge0), 0, 1);
    return t * t * (3 - 2 * t);
};
const asciiCharFor = (value, offset, time)=>{
    const drift = (Math.sin(time * 0.003 + offset) + 1) * 0.08;
    const index = Math.floor(clamp(value + drift, 0, 1) * (ASCII_RAMP.length - 1));
    return ASCII_RAMP[index];
};
const buildBrightnessGrid = (width, height, progress)=>{
    const cols = Math.max(1, Math.ceil(width / CELL_SIZE));
    const rows = Math.max(1, Math.ceil(height / CELL_SIZE));
    const minSide = Math.max(1, Math.min(width, height));
    const centerX = width * 0.52;
    const centerY = height * 0.5;
    const radius = 0.58 + smoothstep(0.12, 0.88, progress) * 0.18;
    return Array.from({
        length: rows
    }, (_rowValue, row)=>Array.from({
            length: cols
        }, (_colValue, col)=>{
            const x = col * CELL_SIZE + CELL_SIZE * 0.5;
            const y = row * CELL_SIZE + CELL_SIZE * 0.5;
            const px = (x - centerX) * 2 / minSide;
            const py = (y - centerY) * 2 / minSide;
            const ringAngle = Math.atan2(py, px);
            const ringWobble = Math.sin(ringAngle * 7 + progress * 2.4) * 0.026 + Math.sin(ringAngle * 19 - progress * 1.7) * 0.012;
            const ringField = Math.abs(Math.hypot(px, py) - radius - ringWobble);
            const ringMask = smoothstep(0.21, 0.035, ringField);
            const shard = Math.sin((x - y * 1.72) * 0.018) * 0.5 + Math.sin(x * 0.015 + y * 0.006 + ringAngle * 5) * 0.5;
            const lane = smoothstep(-0.18, 0.92, shard);
            const backgroundShard = Math.sin((x - y * 1.58) * 0.015) * 0.5 + Math.cos(x * 0.006 + y * 0.021 - progress * 4) * 0.5;
            const backgroundLane = smoothstep(0.72, 0.99, backgroundShard) * 0.28;
            const crossCut = 1 - smoothstep(0.028, 0.13, Math.abs(Math.sin(ringAngle * 9 + progress * 3.1)));
            return clamp(backgroundLane + ringMask * (0.44 + lane * 1.08) + crossCut * ringMask * 0.18, 0, 1);
        }));
};
const createParticles = (width, height)=>{
    const target = clamp(Math.floor(width * height / 320), 1600, 4800);
    return Array.from({
        length: target
    }, ()=>({
            brightness: 0,
            charOffset: Math.random() * 1000,
            depth: 0.62 + Math.random() * 0.86,
            speed: 0,
            x: Math.random() * width,
            y: Math.random() * height
        }));
};
const AsciiFlowCanvas = ({ progress })=>{
    _s();
    const canvasRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useRef"])(null);
    const progressRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useRef"])(progress);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "AsciiFlowCanvas.useEffect": ()=>{
            progressRef.current = progress;
        }
    }["AsciiFlowCanvas.useEffect"], [
        progress
    ]);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "AsciiFlowCanvas.useEffect": ()=>{
            const canvas = canvasRef.current;
            const ctx = canvas?.getContext("2d", {
                alpha: true
            });
            if (!canvas || !ctx) {
                return ({
                    "AsciiFlowCanvas.useEffect": ()=>{
                    // No canvas context was created.
                    }
                })["AsciiFlowCanvas.useEffect"];
            }
            const pointer = {
                x: 0.72,
                y: 0.2
            };
            const flow = {
                x: 0.44,
                y: -0.9
            };
            let width = 0;
            let height = 0;
            let dpr = 1;
            let particles = [];
            let brightnessGrid = [];
            let animationId = 0;
            let lastGridProgress = -1;
            const refreshGrid = {
                "AsciiFlowCanvas.useEffect.refreshGrid": ()=>{
                    const nextProgress = Math.round(progressRef.current * 100) / 100;
                    if (nextProgress === lastGridProgress && brightnessGrid.length > 0) return;
                    lastGridProgress = nextProgress;
                    brightnessGrid = buildBrightnessGrid(width, height, progressRef.current);
                }
            }["AsciiFlowCanvas.useEffect.refreshGrid"];
            const resize = {
                "AsciiFlowCanvas.useEffect.resize": ()=>{
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
                }
            }["AsciiFlowCanvas.useEffect.resize"];
            const move = {
                "AsciiFlowCanvas.useEffect.move": (event)=>{
                    pointer.x = event.clientX / Math.max(1, width);
                    pointer.y = event.clientY / Math.max(1, height);
                }
            }["AsciiFlowCanvas.useEffect.move"];
            const render = {
                "AsciiFlowCanvas.useEffect.render": (time)=>{
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
                    for (const particle of particles){
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
                }
            }["AsciiFlowCanvas.useEffect.render"];
            resize();
            window.addEventListener("pointermove", move, {
                passive: true
            });
            window.addEventListener("resize", resize, {
                passive: true
            });
            animationId = window.requestAnimationFrame(render);
            return ({
                "AsciiFlowCanvas.useEffect": ()=>{
                    if (animationId) window.cancelAnimationFrame(animationId);
                    window.removeEventListener("pointermove", move);
                    window.removeEventListener("resize", resize);
                }
            })["AsciiFlowCanvas.useEffect"];
        }
    }["AsciiFlowCanvas.useEffect"], []);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("canvas", {
        ref: canvasRef,
        "aria-hidden": "true",
        className: "ascii-flow-canvas"
    }, void 0, false, {
        fileName: "[project]/src/landing/AsciiFlowCanvas.tsx",
        lineNumber: 230,
        columnNumber: 5
    }, ("TURBOPACK compile-time value", void 0));
};
_s(AsciiFlowCanvas, "zDt1/gX72jmfkH8o+QTqHvVDGic=");
_c = AsciiFlowCanvas;
const __TURBOPACK__default__export__ = /*#__PURE__*/ _c1 = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["memo"])(AsciiFlowCanvas);
var _c, _c1;
__turbopack_context__.k.register(_c, "AsciiFlowCanvas");
__turbopack_context__.k.register(_c1, "%default%");
if (typeof globalThis.$RefreshHelpers$ === 'object' && globalThis.$RefreshHelpers !== null) {
    __turbopack_context__.k.registerExports(__turbopack_context__.m, globalThis.$RefreshHelpers$);
}
}),
"[project]/src/landing/FractureRingCanvas.tsx [app-client] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "default",
    ()=>__TURBOPACK__default__export__
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/next@16.2.6_@playwright+test@1.60.0_react-dom@19.2.6_react@19.2.6__react@19.2.6/node_modules/next/dist/compiled/react/jsx-dev-runtime.js [app-client] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/next@16.2.6_@playwright+test@1.60.0_react-dom@19.2.6_react@19.2.6__react@19.2.6/node_modules/next/dist/compiled/react/index.js [app-client] (ecmascript)");
;
var _s = __turbopack_context__.k.signature();
;
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
const createShader = (gl, source, type)=>{
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
const createProgram = (gl)=>{
    const vertexShader = createShader(gl, vertexShaderSource, gl.VERTEX_SHADER);
    const fragmentShader = createShader(gl, fragmentShaderSource, gl.FRAGMENT_SHADER);
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
const FractureRingCanvas = ({ progress })=>{
    _s();
    var _s1 = __turbopack_context__.k.signature();
    const canvasRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useRef"])(null);
    const progressRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useRef"])(progress);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "FractureRingCanvas.useEffect": ()=>{
            progressRef.current = progress;
        }
    }["FractureRingCanvas.useEffect"], [
        progress
    ]);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])(_s1({
        "FractureRingCanvas.useEffect": ()=>{
            _s1();
            const canvas = canvasRef.current;
            const gl = canvas?.getContext("webgl", {
                alpha: true,
                antialias: false,
                powerPreference: "high-performance"
            });
            if (!canvas || !gl) {
                return ({
                    "FractureRingCanvas.useEffect": ()=>{
                    // No canvas context was created.
                    }
                })["FractureRingCanvas.useEffect"];
            }
            const program = createProgram(gl);
            if (!program) {
                return ({
                    "FractureRingCanvas.useEffect": ()=>{
                    // Shader compilation failed before resources were allocated.
                    }
                })["FractureRingCanvas.useEffect"];
            }
            const positionLocation = gl.getAttribLocation(program, "position");
            const positionBuffer = gl.createBuffer();
            if (!positionBuffer || positionLocation < 0) {
                gl.deleteProgram(program);
                return ({
                    "FractureRingCanvas.useEffect": ()=>{
                    // Buffer allocation failed after program creation.
                    }
                })["FractureRingCanvas.useEffect"];
            }
            const resolutionLocation = gl.getUniformLocation(program, "resolution");
            const pointerLocation = gl.getUniformLocation(program, "pointer");
            const progressLocation = gl.getUniformLocation(program, "progress");
            const timeLocation = gl.getUniformLocation(program, "time");
            const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
            const pointer = {
                x: 0.5,
                y: 0.5
            };
            let animationId = 0;
            let start = performance.now();
            gl.useProgram(program);
            gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
            gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
                -1,
                -1,
                1,
                -1,
                -1,
                1,
                1,
                -1,
                -1,
                1,
                1,
                1
            ]), gl.STATIC_DRAW);
            gl.enableVertexAttribArray(positionLocation);
            gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);
            const resize = {
                "FractureRingCanvas.useEffect.resize": ()=>{
                    const dpr = Math.min(window.devicePixelRatio || 1, 2);
                    const width = Math.floor(window.innerWidth * dpr);
                    const height = Math.floor(window.innerHeight * dpr);
                    canvas.width = width;
                    canvas.height = height;
                    gl.viewport(0, 0, width, height);
                    gl.uniform2f(resolutionLocation, width, height);
                }
            }["FractureRingCanvas.useEffect.resize"];
            const move = {
                "FractureRingCanvas.useEffect.move": (event)=>{
                    pointer.x = event.clientX / window.innerWidth;
                    pointer.y = 1 - event.clientY / window.innerHeight;
                }
            }["FractureRingCanvas.useEffect.move"];
            const render = {
                "FractureRingCanvas.useEffect.render": ()=>{
                    const elapsed = reduce ? 0 : (performance.now() - start) * 0.001;
                    gl.clearColor(0, 0, 0, 0);
                    gl.clear(gl.COLOR_BUFFER_BIT);
                    gl.uniform1f(timeLocation, elapsed);
                    gl.uniform1f(progressLocation, progressRef.current);
                    gl.uniform2f(pointerLocation, pointer.x, pointer.y);
                    gl.drawArrays(gl.TRIANGLES, 0, 6);
                    animationId = window.requestAnimationFrame(render);
                }
            }["FractureRingCanvas.useEffect.render"];
            resize();
            start = performance.now();
            render();
            window.addEventListener("pointermove", move, {
                passive: true
            });
            window.addEventListener("resize", resize, {
                passive: true
            });
            return ({
                "FractureRingCanvas.useEffect": ()=>{
                    if (animationId) window.cancelAnimationFrame(animationId);
                    window.removeEventListener("pointermove", move);
                    window.removeEventListener("resize", resize);
                    gl.deleteBuffer(positionBuffer);
                    gl.deleteProgram(program);
                }
            })["FractureRingCanvas.useEffect"];
        }
    }["FractureRingCanvas.useEffect"], "ZdQBZ3rq7bWAAMQq6hlVCmYF0jM=", true), []);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("canvas", {
        ref: canvasRef,
        "aria-hidden": "true",
        className: "fracture-ring-canvas"
    }, void 0, false, {
        fileName: "[project]/src/landing/FractureRingCanvas.tsx",
        lineNumber: 241,
        columnNumber: 5
    }, ("TURBOPACK compile-time value", void 0));
};
_s(FractureRingCanvas, "zDt1/gX72jmfkH8o+QTqHvVDGic=");
_c = FractureRingCanvas;
const __TURBOPACK__default__export__ = /*#__PURE__*/ _c1 = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["memo"])(FractureRingCanvas);
var _c, _c1;
__turbopack_context__.k.register(_c, "FractureRingCanvas");
__turbopack_context__.k.register(_c1, "%default%");
if (typeof globalThis.$RefreshHelpers$ === 'object' && globalThis.$RefreshHelpers !== null) {
    __turbopack_context__.k.registerExports(__turbopack_context__.m, globalThis.$RefreshHelpers$);
}
}),
"[project]/src/api.ts [app-client] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "api",
    ()=>api,
    "connectRunStream",
    ()=>connectRunStream,
    "connectSystemStream",
    ()=>connectSystemStream,
    "resolveBaseUrl",
    ()=>resolveBaseUrl
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$build$2f$polyfills$2f$process$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = /*#__PURE__*/ __turbopack_context__.i("[project]/node_modules/.pnpm/next@16.2.6_@playwright+test@1.60.0_react-dom@19.2.6_react@19.2.6__react@19.2.6/node_modules/next/dist/build/polyfills/process.js [app-client] (ecmascript)");
const DEFAULT_API_BASE_URL = ("TURBOPACK compile-time value", "http://127.0.0.1:8787") ?? "http://127.0.0.1:8787";
const DEFAULT_LOCAL_OPERATOR_ID = "local-operator";
const DEFAULT_LOCAL_OPERATOR_ROLES = "viewer,launcher,approver";
const LOCAL_OPERATOR_HOSTS = new Set([
    "localhost",
    "127.0.0.1",
    "::1"
]);
function resolveBaseUrl() {
    if ("TURBOPACK compile-time falsy", 0) //TURBOPACK unreachable
    ;
    const params = new URLSearchParams(window.location.search);
    const server = params.get("server");
    if (server) {
        return server.replace(/\/+$/, "");
    }
    if ("TURBOPACK compile-time truthy", 1) {
        return DEFAULT_API_BASE_URL.replace(/\/+$/, "");
    }
    //TURBOPACK unreachable
    ;
}
function isLocalOperatorSurface() {
    if ("TURBOPACK compile-time falsy", 0) //TURBOPACK unreachable
    ;
    return LOCAL_OPERATOR_HOSTS.has(window.location.hostname);
}
function queryOrStorageValue(params, queryName, storageName) {
    const queryValue = params.get(queryName);
    if (queryValue !== null) {
        return queryValue.trim();
    }
    try {
        return window.localStorage.getItem(storageName)?.trim() ?? "";
    } catch  {
        return "";
    }
}
function operatorIdentityHeaders() {
    const envOperator = __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$build$2f$polyfills$2f$process$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["default"].env.NEXT_PUBLIC_MESH_OPERATOR_ID?.trim() ?? "";
    const envRoles = __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$build$2f$polyfills$2f$process$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["default"].env.NEXT_PUBLIC_MESH_OPERATOR_ROLES?.trim() ?? "";
    if ("TURBOPACK compile-time falsy", 0) //TURBOPACK unreachable
    ;
    const params = new URLSearchParams(window.location.search);
    const operatorId = queryOrStorageValue(params, "operator", "mesh.operator.id") || queryOrStorageValue(params, "operator_id", "mesh.operator.id") || envOperator || (isLocalOperatorSurface() ? DEFAULT_LOCAL_OPERATOR_ID : "");
    const roles = queryOrStorageValue(params, "roles", "mesh.operator.roles") || queryOrStorageValue(params, "operator_roles", "mesh.operator.roles") || envRoles || (isLocalOperatorSurface() ? DEFAULT_LOCAL_OPERATOR_ROLES : "");
    return operatorId && roles ? {
        "X-Mesh-Operator": operatorId,
        "X-Mesh-Roles": roles
    } : {};
}
function jsonHeaders(init) {
    return {
        "Content-Type": "application/json",
        ...operatorIdentityHeaders(),
        ...init?.headers ?? {}
    };
}
async function request(baseUrl, path, init) {
    const response = await fetch(`${baseUrl}${path}`, {
        headers: jsonHeaders(init),
        ...init
    });
    if (!response.ok) {
        let detail = `${response.status} ${response.statusText}`;
        try {
            const body = await response.json();
            if (body?.detail) detail = body.detail;
            else if (body?.error) detail = body.error;
            else if (body?.message) detail = body.message;
        } catch  {
        /* body not JSON */ }
        throw new Error(detail);
    }
    return await response.json();
}
async function requestAllowingStatus(baseUrl, path, allowedStatuses, init) {
    const response = await fetch(`${baseUrl}${path}`, {
        headers: jsonHeaders(init),
        ...init
    });
    if (!response.ok && !allowedStatuses.includes(response.status)) {
        let detail = `${response.status} ${response.statusText}`;
        try {
            const body = await response.json();
            if (body?.detail) detail = body.detail;
            else if (body?.error) detail = body.error;
            else if (body?.message) detail = body.message;
        } catch  {
        /* body not JSON */ }
        throw new Error(detail);
    }
    return await response.json();
}
async function requestBlob(baseUrl, path, init) {
    const response = await fetch(`${baseUrl}${path}`, {
        headers: jsonHeaders(init),
        ...init
    });
    if (!response.ok) {
        let detail = `${response.status} ${response.statusText}`;
        try {
            const body = await response.json();
            if (body?.detail) detail = body.detail;
            else if (body?.error) detail = body.error;
            else if (body?.message) detail = body.message;
        } catch  {
        /* body not JSON */ }
        throw new Error(detail);
    }
    const disposition = response.headers.get("Content-Disposition") ?? "";
    const match = disposition.match(/filename="([^"]+)"/);
    return {
        blob: await response.blob(),
        filename: match?.[1] ?? "mesh-run-export.zip"
    };
}
const api = {
    getHealth (baseUrl) {
        return request(baseUrl, "/api/health");
    },
    getReadiness (baseUrl) {
        return request(baseUrl, "/api/readiness");
    },
    getConnectorCertification (baseUrl) {
        return request(baseUrl, "/api/connectors/certification");
    },
    getApprovals (baseUrl) {
        return request(baseUrl, "/api/approvals");
    },
    getKillSwitch (baseUrl) {
        return request(baseUrl, "/api/kill-switch");
    },
    applyKillSwitch (baseUrl, payload) {
        return request(baseUrl, "/api/kill-switch", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    simulatePolicy (baseUrl, payload) {
        return request(baseUrl, "/api/policy/simulate", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    getPilotGoNoGo (baseUrl) {
        return request(baseUrl, "/api/pilot/go-no-go");
    },
    getTrustLadder (baseUrl) {
        return request(baseUrl, "/api/trust-ladder");
    },
    getScenarios (baseUrl) {
        return request(baseUrl, "/api/scenarios");
    },
    getSimulations (baseUrl) {
        return request(baseUrl, "/api/simulations");
    },
    runSimulation (baseUrl, scenarioId, payload) {
        return request(baseUrl, `/api/simulations/${encodeURIComponent(scenarioId)}/run`, {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    getBenchmarks (baseUrl) {
        return request(baseUrl, "/api/benchmarks");
    },
    getBenchmark (baseUrl, benchmarkId) {
        return request(baseUrl, `/api/benchmarks/${encodeURIComponent(benchmarkId)}`);
    },
    getServiceAgents (baseUrl) {
        return request(baseUrl, "/api/service-agents");
    },
    getGoals (baseUrl) {
        return request(baseUrl, "/api/goals");
    },
    createGoal (baseUrl, payload) {
        return request(baseUrl, "/api/goals", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    getRuns (baseUrl) {
        return request(baseUrl, "/api/runs");
    },
    getResearchSessions (baseUrl) {
        return request(baseUrl, "/api/research-sessions");
    },
    getResearchCorpus (baseUrl) {
        return request(baseUrl, "/api/research-corpus");
    },
    getResearchSession (baseUrl, sessionId) {
        const id = encodeURIComponent(sessionId);
        return request(baseUrl, `/api/research-sessions/${id}`);
    },
    createRun (baseUrl, payload) {
        return request(baseUrl, "/api/runs", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    runMeshBrainModelKernelProbe (baseUrl, payload = {}) {
        return request(baseUrl, "/api/mesh-brain/model-kernel-probe", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    runMeshBrainLiveServingSmoke (baseUrl, payload = {}) {
        return request(baseUrl, "/api/mesh-brain/live-serving-smoke", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    runMeshBrainRollbackDrill (baseUrl, payload = {}) {
        return request(baseUrl, "/api/mesh-brain/rollback-drill", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    runMeshBrainBackendMatrix (baseUrl, payload = {}) {
        return request(baseUrl, "/api/mesh-brain/backend-matrix", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    getRun (baseUrl, runId) {
        return request(baseUrl, `/api/runs/${runId}`);
    },
    getRunExport (baseUrl, runId) {
        return request(baseUrl, `/api/runs/${runId}/export`, {
            method: "POST",
            body: JSON.stringify({})
        });
    },
    getRunDarkharnessPacket (baseUrl, runId) {
        return requestAllowingStatus(baseUrl, `/api/runs/${runId}/darkharness-packet`, [
            409
        ]);
    },
    getRunDeliveryContext (baseUrl, runId) {
        return request(baseUrl, `/api/runs/${encodeURIComponent(runId)}/delivery-context`);
    },
    getRunExportArchive (baseUrl, runId) {
        return requestBlob(baseUrl, `/api/runs/${runId}/export/archive`, {
            method: "POST",
            body: JSON.stringify({})
        });
    },
    steerRun (baseUrl, runId, payload) {
        return request(baseUrl, `/api/runs/${runId}/steer`, {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    getRunEvents (baseUrl, runId) {
        return request(baseUrl, `/api/runs/${runId}/events`);
    },
    getRunMerkle (baseUrl, runId) {
        return request(baseUrl, `/api/runs/${runId}/merkle`);
    },
    getScenarioAnalysis (baseUrl, runId) {
        return request(baseUrl, `/api/runs/${runId}/scenario-analysis`);
    },
    getEvidenceGraph (baseUrl, runId) {
        return request(baseUrl, `/api/runs/${runId}/evidence-graph`);
    },
    getMemoryCrystallization (baseUrl, runId) {
        return request(baseUrl, `/api/runs/${runId}/memory-crystallization`);
    },
    getAgentTasks (baseUrl, runId) {
        return request(baseUrl, `/api/runs/${runId}/agent-tasks`);
    },
    getWatchers (baseUrl) {
        return request(baseUrl, "/api/watchers");
    },
    getMerkleProof (baseUrl, runId, eventId) {
        return request(baseUrl, `/api/runs/${runId}/merkle/proof/${eventId}`);
    },
    getVaultTree (baseUrl) {
        return request(baseUrl, "/api/vault/tree");
    },
    getVaultDocument (baseUrl, path) {
        const query = new URLSearchParams({
            path
        });
        return request(baseUrl, `/api/vault/document?${query.toString()}`);
    }
};
function connectSystemStream(baseUrl, handlers) {
    const source = new EventSource(`${baseUrl}/api/stream/system`);
    source.onopen = ()=>handlers.onOpen?.();
    source.onerror = ()=>handlers.onError?.();
    source.onmessage = (event)=>{
        handlers.onSnapshot(JSON.parse(event.data));
    };
    source.addEventListener("system", (event)=>{
        const message = event;
        handlers.onSnapshot(JSON.parse(message.data));
    });
    return ()=>source.close();
}
function connectRunStream(baseUrl, runId, handlers) {
    const source = new EventSource(`${baseUrl}/api/stream/runs/${runId}`);
    source.onopen = ()=>handlers.onOpen?.();
    source.onerror = ()=>handlers.onError?.();
    source.onmessage = ()=>handlers.onEvent();
    source.addEventListener("complete", ()=>handlers.onEvent());
    return ()=>source.close();
}
if (typeof globalThis.$RefreshHelpers$ === 'object' && globalThis.$RefreshHelpers !== null) {
    __turbopack_context__.k.registerExports(__turbopack_context__.m, globalThis.$RefreshHelpers$);
}
}),
"[project]/src/lib/format.ts [app-client] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "formatDuration",
    ()=>formatDuration,
    "formatTimestamp",
    ()=>formatTimestamp,
    "humanize",
    ()=>humanize,
    "relativeTime",
    ()=>relativeTime,
    "riskColor",
    ()=>riskColor,
    "safeJsonParse",
    ()=>safeJsonParse,
    "stageIcon",
    ()=>stageIcon,
    "truncateHash",
    ()=>truncateHash
]);
function relativeTime(iso) {
    const date = new Date(iso);
    const diff = Date.now() - date.getTime();
    if (diff < 0) return "upcoming";
    if (diff < 60_000) return "just now";
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
    return date.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric"
    });
}
function formatTimestamp(iso) {
    return new Date(iso).toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
    });
}
function formatDuration(startIso, endIso) {
    const start = new Date(startIso).getTime();
    const end = endIso ? new Date(endIso).getTime() : Date.now();
    const ms = end - start;
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
    if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ${Math.floor(ms % 60_000 / 1000)}s`;
    return `${Math.floor(ms / 3_600_000)}h ${Math.floor(ms % 3_600_000 / 60_000)}m`;
}
function truncateHash(hash, len = 12) {
    if (hash.length <= len) return hash;
    return hash.slice(0, len) + "…";
}
function humanize(snakeCase) {
    return snakeCase.replace(/_/g, " ").replace(/\b\w/g, (c)=>c.toUpperCase());
}
function safeJsonParse(text) {
    try {
        return {
            ok: true,
            data: JSON.parse(text)
        };
    } catch (e) {
        return {
            ok: false,
            error: e instanceof Error ? e.message : "Invalid JSON"
        };
    }
}
function riskColor(level) {
    switch(level?.toLowerCase()){
        case "critical":
        case "high":
            return "var(--accent-danger)";
        case "medium":
            return "var(--accent-warm)";
        case "low":
            return "var(--accent-good)";
        default:
            return "var(--muted)";
    }
}
function stageIcon(stage) {
    const icons = {
        queued: "◦",
        ingesting: "↓",
        trigger_ready: "⚡",
        evidence_pack_ready: "◇",
        investigation_ready: "⌕",
        scenario_analysis_ready: "◆",
        decision_ready: "◈",
        evaluation_ready: "✓",
        awaiting_operator: "⏸",
        executing: "▶",
        feedback_ready: "◉",
        completed: "●",
        failed: "✕",
        cancelled: "⊘",
        no_trigger: "○"
    };
    return icons[stage] ?? "·";
}
if (typeof globalThis.$RefreshHelpers$ === 'object' && globalThis.$RefreshHelpers !== null) {
    __turbopack_context__.k.registerExports(__turbopack_context__.m, globalThis.$RefreshHelpers$);
}
}),
"[project]/src/lib/labyrinth.ts [app-client] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "buildLabyrinthCrossings",
    ()=>buildLabyrinthCrossings,
    "buildLabyrinthGuideposts",
    ()=>buildLabyrinthGuideposts,
    "buildLabyrinthJourneys",
    ()=>buildLabyrinthJourneys,
    "crossingFromEvent",
    ()=>crossingFromEvent
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$lib$2f$format$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/lib/format.ts [app-client] (ecmascript)");
;
function buildLabyrinthJourneys({ runs, researchSessions, watchers, activeRunId, activeResearchSessionId }) {
    const runJourneys = runs.map((run)=>({
            id: run.run_id,
            kind: "run",
            source: run.scenario_key ? "scenario" : "manual",
            title: run.scenario_key ? (0, __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$lib$2f$format$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["humanize"])(run.scenario_key) : "Manual run",
            status: run.status,
            summary: `${(0, __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$lib$2f$format$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["humanize"])(run.stage)} - ${run.latest_event_sequence} events`,
            updated_at: run.updated_at,
            event_count: run.latest_event_sequence,
            risk_level: riskFromArtifacts(run.artifacts ?? {}),
            selected: run.run_id === activeRunId
        }));
    const researchJourneys = researchSessions.map((session)=>({
            id: session.session_id,
            kind: "research",
            source: session.minimax_route ?? "research",
            title: session.question || session.directory,
            status: session.status,
            summary: session.research_intelligence ? (0, __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$lib$2f$format$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["humanize"])(session.research_intelligence.classification) : session.has_final_report ? "Final report ready" : "Research in progress",
            updated_at: session.updated_at,
            event_count: session.has_final_report ? 1 : 0,
            risk_level: session.research_intelligence?.classification === "off_domain" ? "medium" : null,
            selected: session.session_id === activeResearchSessionId
        }));
    const watcherJourneys = (watchers?.watchers ?? []).map((watcher)=>({
            id: watcher.name,
            kind: "watcher",
            source: watcher.signal_source,
            title: watcher.name,
            status: watcher.running ? "running" : "stopped",
            summary: `${watcher.signal_source} every ${watcher.interval_seconds}s`,
            updated_at: "",
            event_count: Number(watcher.detail?.dedup_entries ?? 0),
            risk_level: watcher.running ? null : "medium",
            selected: false
        }));
    return [
        ...runJourneys,
        ...researchJourneys,
        ...watcherJourneys
    ];
}
function buildLabyrinthCrossings({ run, scenarioAnalysis, evidenceGraph, memoryCrystallization, watchers }) {
    const crossings = [];
    const journeyId = run?.run_id ?? "mesh";
    (run?.events ?? []).forEach((event)=>{
        crossings.push(crossingFromEvent(event));
    });
    (scenarioAnalysis?.evidence_nodes ?? []).forEach((node, index)=>{
        const evidenceId = String(node.evidence_id ?? `evidence-${index}`);
        crossings.push({
            id: evidenceId,
            journey_id: journeyId,
            type: "evidence",
            label: String(node.summary ?? node.kind ?? "Evidence"),
            status: node.trusted === false ? "untrusted" : "trusted",
            thread: "evidence",
            sequence: crossings.length + 1,
            actor: String(node.analyzer ?? "analyzer"),
            target: String(node.kind ?? "evidence"),
            preview_in: formatPreview(node.payload),
            preview_out: String(node.summary ?? ""),
            event_id: null,
            artifact_key: "scenario_analysis",
            evidence_refs: [
                evidenceId
            ],
            severity: severityFromConfidence(Number(node.confidence ?? 0.5), node.trusted === false)
        });
    });
    (evidenceGraph?.nodes ?? []).filter((node)=>node.type === "subdecision" || node.type === "scenario_analysis").forEach((node)=>{
        crossings.push({
            id: node.id,
            journey_id: journeyId,
            type: node.type,
            label: String(node.label ?? (0, __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$lib$2f$format$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["humanize"])(node.type)),
            status: node.requires_review ? "requires_review" : "recorded",
            thread: node.requires_review ? "threshold" : "evidence",
            sequence: crossings.length + 1,
            actor: node.analyzer ?? "scenario_analysis",
            target: node.type,
            preview_in: node.confidence != null ? `confidence ${node.confidence}` : null,
            preview_out: node.merkle_root ?? null,
            event_id: null,
            artifact_key: "evidence_graph",
            evidence_refs: evidenceGraph ? evidenceRefsForNode(evidenceGraph, node.id) : [],
            severity: node.requires_review ? "warning" : "info"
        });
    });
    if (memoryCrystallization) {
        crossings.push({
            id: `${journeyId}:memory-crystallization`,
            journey_id: journeyId,
            type: "memory_crystallization",
            label: "Memory crystallization",
            status: "recorded",
            thread: "memory",
            sequence: crossings.length + 1,
            actor: "memory",
            target: "vault",
            preview_in: formatPreview(memoryCrystallization),
            preview_out: `${Object.keys(memoryCrystallization).length} fields`,
            event_id: null,
            artifact_key: "memory_crystallization",
            evidence_refs: [],
            severity: "success"
        });
    }
    (watchers?.watchers ?? []).forEach((watcher)=>{
        crossings.push({
            id: `watcher:${watcher.name}`,
            journey_id: watcher.name,
            type: "watcher",
            label: watcher.name,
            status: watcher.running ? "running" : "stopped",
            thread: "watcher",
            sequence: crossings.length + 1,
            actor: watcher.signal_source,
            target: "control_plane",
            preview_in: formatPreview(watcher.detail),
            preview_out: `${watcher.signal_source} / ${watcher.interval_seconds}s`,
            event_id: null,
            artifact_key: null,
            evidence_refs: [],
            severity: watcher.running ? "success" : "warning"
        });
    });
    return crossings;
}
function buildLabyrinthGuideposts({ run, scenarioAnalysis, evidenceGraph, watchers }) {
    const journeyId = run?.run_id ?? "mesh";
    const guideposts = [];
    if (run?.stage === "awaiting_operator") {
        guideposts.push({
            id: `${journeyId}:operator-gate`,
            journey_id: journeyId,
            severity: "warning",
            title: "Operator gate is active",
            detail: "The run is paused at a threshold and requires steering before actuation continues.",
            evidence_refs: [
                run.latest_event_id ?? ""
            ].filter(Boolean)
        });
    }
    if (run?.status === "failed" || run?.stage === "failed") {
        guideposts.push({
            id: `${journeyId}:failed`,
            journey_id: journeyId,
            severity: "danger",
            title: "Run failed",
            detail: run.error ?? "The run reached a failed terminal state.",
            evidence_refs: [
                run.latest_event_id ?? ""
            ].filter(Boolean)
        });
    }
    const scenarioEvidenceRefs = scenarioAnalysis?.evidence_refs ?? [];
    (scenarioAnalysis?.required_review_reasons ?? []).forEach((reason, index)=>{
        guideposts.push({
            id: `${journeyId}:review-${index}`,
            journey_id: journeyId,
            severity: "warning",
            title: "Review required",
            detail: reason,
            evidence_refs: scenarioEvidenceRefs
        });
    });
    (scenarioAnalysis?.evidence_nodes ?? []).filter((node)=>node.trusted === false || Number(node.confidence ?? 1) < 0.6).forEach((node, index)=>{
        guideposts.push({
            id: `${journeyId}:weak-evidence-${index}`,
            journey_id: journeyId,
            severity: "warning",
            title: "Weak evidence",
            detail: String(node.summary ?? "Evidence has low confidence or is untrusted."),
            evidence_refs: [
                String(node.evidence_id ?? "")
            ].filter(Boolean)
        });
    });
    const reviewSubdecisions = (evidenceGraph?.nodes ?? []).filter((node)=>node.requires_review);
    if (reviewSubdecisions.length > 0) {
        guideposts.push({
            id: `${journeyId}:subdecision-review`,
            journey_id: journeyId,
            severity: "warning",
            title: "Subdecision routed to review",
            detail: `${reviewSubdecisions.length} scenario analysis subdecision(s) require review.`,
            evidence_refs: reviewSubdecisions.map((node)=>node.id)
        });
    }
    const stoppedWatchers = (watchers?.watchers ?? []).filter((watcher)=>!watcher.running);
    if (stoppedWatchers.length > 0) {
        guideposts.push({
            id: "watchers:stopped",
            journey_id: "watchers",
            severity: "warning",
            title: "Watcher coverage reduced",
            detail: `${stoppedWatchers.length} registered watcher(s) are stopped.`,
            evidence_refs: stoppedWatchers.map((watcher)=>watcher.name)
        });
    }
    return guideposts.slice(0, 12);
}
function crossingFromEvent(event) {
    return {
        id: event.event_id,
        journey_id: event.run_id,
        type: event.event_type,
        label: (0, __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$lib$2f$format$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["humanize"])(event.event_type),
        status: event.status ?? "recorded",
        thread: threadForEvent(event),
        sequence: event.sequence,
        recorded_at: event.recorded_at,
        actor: event.integration_name ?? "mesh",
        target: event.artifact_key ?? event.stage,
        preview_in: formatPreview(event.payload),
        preview_out: formatPreview(event.summary),
        event_id: event.event_id,
        artifact_key: event.artifact_key ?? null,
        evidence_refs: event.merkle_leaf_hash ? [
            event.merkle_leaf_hash
        ] : [],
        severity: severityForEvent(event)
    };
}
function threadForEvent(event) {
    if (event.stage === "awaiting_operator" || event.event_type.includes("approval")) return "threshold";
    if (event.artifact_key === "scenario_analysis" || event.event_type.includes("evidence")) return "evidence";
    if (event.artifact_key === "memory_crystallization" || event.event_type.includes("memory")) return "memory";
    if (event.stage === "executing" || event.artifact_key === "execution") return "execution";
    return "main";
}
function severityForEvent(event) {
    if (event.stage === "failed" || event.status === "failed" || event.event_type.includes("blocked")) return "danger";
    if (event.stage === "awaiting_operator" || event.status === "requires_review") return "warning";
    if (event.stage === "completed" || event.status === "recorded") return "success";
    return "info";
}
function severityFromConfidence(confidence, untrusted) {
    if (untrusted) return "danger";
    if (confidence < 0.6) return "warning";
    if (confidence >= 0.8) return "success";
    return "info";
}
function evidenceRefsForNode(graph, nodeId) {
    return graph.edges.filter((edge)=>edge.target === nodeId || edge.source === nodeId).flatMap((edge)=>[
            edge.source,
            edge.target
        ]).filter((id)=>id !== nodeId);
}
function riskFromArtifacts(artifacts) {
    if (!artifacts) return null;
    const scenario = artifacts.scenario_analysis;
    if (scenario && typeof scenario === "object" && typeof scenario.risk_level === "string") return scenario.risk_level;
    const decision = artifacts.decision;
    if (decision && typeof decision === "object" && typeof decision.risk?.level === "string") return decision.risk.level;
    return null;
}
function formatPreview(value) {
    if (value == null) return "";
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`;
    if (typeof value === "object") return `${Object.keys(value).length} fields`;
    return "";
}
if (typeof globalThis.$RefreshHelpers$ === 'object' && globalThis.$RefreshHelpers !== null) {
    __turbopack_context__.k.registerExports(__turbopack_context__.m, globalThis.$RefreshHelpers$);
}
}),
"[project]/src/lib/runGraph.ts [app-client] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "buildArtifactGraph",
    ()=>buildArtifactGraph,
    "buildEvidenceGraph",
    ()=>buildEvidenceGraph,
    "buildKubernetesGraph",
    ()=>buildKubernetesGraph,
    "buildLabyrinthGraph",
    ()=>buildLabyrinthGraph,
    "buildMerkleGraph",
    ()=>buildMerkleGraph,
    "buildRcaGraph",
    ()=>buildRcaGraph,
    "buildRethSignalGraph",
    ()=>buildRethSignalGraph,
    "buildRunGraph",
    ()=>buildRunGraph,
    "buildUnifiedGraph",
    ()=>buildUnifiedGraph,
    "toneForStage",
    ()=>toneForStage
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f40$xyflow$2b$system$40$0$2e$0$2e$76$2f$node_modules$2f40$xyflow$2f$system$2f$dist$2f$esm$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/@xyflow+system@0.0.76/node_modules/@xyflow/system/dist/esm/index.js [app-client] (ecmascript)");
;
const STAGE_ORDER = [
    "queued",
    "ingesting",
    "trigger_ready",
    "evidence_pack_ready",
    "investigation_ready",
    "scenario_analysis_ready",
    "decision_ready",
    "evaluation_ready",
    "awaiting_operator",
    "executing",
    "feedback_ready",
    "completed",
    "failed",
    "cancelled",
    "no_trigger"
];
const GRAPH_TONE = {
    info: "#548af7",
    active: "#2aacb8",
    cyan: "#2aacb8",
    success: "#73b00a",
    warn: "#e8a33e",
    danger: "#f75464",
    purple: "#c77dbb",
    functionBlue: "#56a8f5",
    neutral: "#7a7e85"
};
function buildRunGraph(events, selectedEventId) {
    const stageCounts = new Map();
    const columnCounts = new Map();
    const nodes = events.map((event)=>{
        const stageIndex = Math.max(STAGE_ORDER.indexOf(event.stage), 0);
        const rowIndex = stageCounts.get(event.stage) ?? 0;
        stageCounts.set(event.stage, rowIndex + 1);
        const columnIndex = columnCounts.get(stageIndex) ?? 0;
        columnCounts.set(stageIndex, columnIndex + 1);
        const tone = toneForStage(event.stage);
        const isSelected = event.event_id === selectedEventId;
        return {
            id: event.event_id,
            type: "runEvent",
            selected: isSelected,
            data: {
                nodeKind: "run",
                title: humanizeToken(event.event_type),
                statusLabel: humanizeToken(event.stage),
                accent: tone,
                meta: compact([
                    `#${event.sequence}`,
                    event.integration_name ?? undefined,
                    event.artifact_key ?? undefined
                ]),
                eventId: event.event_id,
                sequence: event.sequence,
                eventType: event.event_type,
                stage: event.stage,
                recordedAt: event.recorded_at,
                preview: summarizeEvent(event),
                integrationName: event.integration_name,
                artifactKey: event.artifact_key
            },
            position: {
                x: stageIndex * 236,
                y: rowIndex * 146 + (columnIndex % 2 === 0 ? 0 : 18)
            },
            sourcePosition: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f40$xyflow$2b$system$40$0$2e$0$2e$76$2f$node_modules$2f40$xyflow$2f$system$2f$dist$2f$esm$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["Position"].Right,
            targetPosition: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f40$xyflow$2b$system$40$0$2e$0$2e$76$2f$node_modules$2f40$xyflow$2f$system$2f$dist$2f$esm$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["Position"].Left,
            style: {
                width: isSelected ? 212 : 196
            }
        };
    });
    const edges = events.slice(1).map((event, index)=>({
            id: `edge-${events[index].event_id}-${event.event_id}`,
            source: events[index].event_id,
            target: event.event_id,
            type: "smoothstep",
            animated: event.stage === "executing" || event.stage === "awaiting_operator",
            style: {
                stroke: toneForStage(event.stage),
                strokeWidth: event.event_id === selectedEventId || events[index].event_id === selectedEventId ? 2.2 : 1.5,
                opacity: event.event_id === selectedEventId || events[index].event_id === selectedEventId ? 0.95 : 0.6
            }
        }));
    return {
        nodes,
        edges
    };
}
function buildLabyrinthGraph(crossings, selectedCrossingId) {
    if (crossings.length === 0) return {
        nodes: [],
        edges: []
    };
    const laneY = {
        threshold: 0,
        main: 150,
        evidence: 300,
        execution: 450,
        memory: 600,
        watcher: 750
    };
    const laneCounts = new Map();
    const nodes = crossings.map((crossing, index)=>{
        const lane = crossing.thread;
        const rowCount = laneCounts.get(lane) ?? 0;
        laneCounts.set(lane, rowCount + 1);
        const selected = crossing.id === selectedCrossingId || crossing.event_id === selectedCrossingId;
        const tone = toneForSeverity(crossing.severity);
        return canvasNode({
            id: crossing.id,
            kind: crossing.thread === "watcher" ? "kubernetes" : crossing.thread === "evidence" ? "artifact" : "run",
            title: crossing.label,
            statusLabel: humanizeToken(crossing.status),
            preview: crossing.preview_out || crossing.preview_in || crossing.target || crossing.type,
            accent: tone,
            meta: compact([
                `#${crossing.sequence || index + 1}`,
                humanizeToken(crossing.thread),
                crossing.actor ?? undefined
            ]),
            position: {
                x: index * 232,
                y: (laneY[lane] ?? laneY.main) + rowCount % 2 * 28
            },
            eventId: crossing.event_id ?? crossing.id,
            sequence: crossing.sequence,
            eventType: crossing.type,
            stage: crossing.status,
            recordedAt: crossing.recorded_at ?? undefined,
            artifactKey: crossing.artifact_key
        }, selected);
    });
    const edges = crossings.slice(1).map((crossing, index)=>{
        const previous = crossings[index];
        const threshold = crossing.thread === "threshold" || previous.thread === "threshold";
        return canvasEdge(`labyrinth-${previous.id}-${crossing.id}`, previous.id, crossing.id, threshold ? GRAPH_TONE.warn : toneForSeverity(crossing.severity), threshold);
    });
    const evidenceByRef = new Map();
    crossings.forEach((crossing)=>{
        crossing.evidence_refs.forEach((ref)=>evidenceByRef.set(ref, crossing.id));
    });
    crossings.forEach((crossing)=>{
        crossing.evidence_refs.forEach((ref)=>{
            const source = evidenceByRef.get(ref);
            if (source && source !== crossing.id) {
                edges.push(canvasEdge(`evidence-ref-${source}-${crossing.id}`, source, crossing.id, GRAPH_TONE.purple, true));
            }
        });
    });
    return {
        nodes,
        edges
    };
}
function buildEvidenceGraph(graph) {
    if (!graph?.nodes?.length) return {
        nodes: [],
        edges: []
    };
    const nodes = graph.nodes.map((node, index)=>{
        const lane = node.type === "evidence" ? 0 : node.type === "subdecision" ? 1 : 2;
        const tone = node.requires_review ? GRAPH_TONE.warn : node.type === "scenario_analysis" ? GRAPH_TONE.active : GRAPH_TONE.info;
        return canvasNode({
            id: node.id,
            kind: node.type === "scenario_analysis" ? "section" : "artifact",
            title: String(node.label ?? humanizeToken(node.type)),
            statusLabel: humanizeToken(node.type),
            preview: compact([
                node.analyzer ?? undefined,
                typeof node.confidence === "number" ? `confidence ${Math.round(node.confidence * 100)}%` : undefined,
                node.requires_review ? "requires review" : undefined
            ]).join(" / ") || "evidence graph node",
            accent: tone,
            meta: compact([
                node.id,
                node.merkle_root ?? undefined
            ]),
            position: {
                x: lane * 320,
                y: 80 + index * 118
            },
            artifactKey: "evidence_graph"
        });
    });
    const edges = graph.edges.map((edge, index)=>canvasEdge(`evidence-${index}-${edge.source}-${edge.target}`, edge.source, edge.target, edge.kind === "feeds" ? GRAPH_TONE.active : GRAPH_TONE.purple, edge.kind === "feeds"));
    return {
        nodes,
        edges
    };
}
function buildRcaGraph(input) {
    if (!input) return {
        nodes: [],
        edges: []
    };
    const hasContent = input.tools.length > 0 || input.candidates.length > 0 || input.blockers.length > 0 || input.citations.length > 0;
    if (!hasContent) return {
        nodes: [],
        edges: []
    };
    const nodes = [
        canvasNode({
            id: "rca-investigation",
            kind: "section",
            title: "Investigation",
            statusLabel: input.stopReason ? humanizeToken(input.stopReason) : "RCA",
            preview: `${input.tools.length} tools / ${input.candidates.length} candidates`,
            accent: GRAPH_TONE.info,
            meta: compact([
                `${input.blockers.length} blockers`,
                `${input.citations.length} citations`
            ]),
            position: {
                x: 20,
                y: 210
            },
            artifactKey: "investigation_report"
        })
    ];
    const edges = [];
    input.tools.slice(0, 10).forEach((tool, index)=>{
        const id = `rca-tool-${tool.id}`;
        const tone = tool.valid ? GRAPH_TONE.active : GRAPH_TONE.warn;
        nodes.push(canvasNode({
            id,
            kind: "artifact",
            title: tool.name,
            statusLabel: humanizeToken(tool.status || "tool"),
            preview: tool.summary || "read-only diagnostic call",
            accent: tone,
            meta: compact([
                `#${index + 1}`,
                ...tool.citationIds.slice(0, 1)
            ]),
            position: {
                x: 310,
                y: 40 + index * 112
            },
            artifactKey: "tool_trajectory"
        }));
        edges.push(canvasEdge(`rca-investigation-${id}`, "rca-investigation", id, tone, true));
    });
    input.candidates.slice(0, 6).forEach((candidate, index)=>{
        const id = `rca-candidate-${candidate.id}`;
        const confidence = typeof candidate.confidence === "number" ? `${Math.round(candidate.confidence * 100)}%` : "unscored";
        const tone = candidate.rank === 1 ? GRAPH_TONE.success : candidate.rank <= 3 ? GRAPH_TONE.active : GRAPH_TONE.info;
        nodes.push(canvasNode({
            id,
            kind: "artifact",
            title: candidate.cause,
            statusLabel: `Rank ${candidate.rank}`,
            preview: `${confidence} confidence${candidate.support.length ? ` / ${candidate.support.slice(0, 2).join(", ")}` : ""}`,
            accent: tone,
            meta: compact(candidate.citationIds.slice(0, 2)),
            position: {
                x: 650,
                y: 78 + index * 126
            },
            artifactKey: "investigation_report"
        }));
        const linkedTools = input.tools.filter((tool)=>tool.citationIds.some((citationId)=>candidate.citationIds.includes(citationId)) || candidate.support.some((support)=>tool.name.toLowerCase().includes(support.toLowerCase())));
        const sources = linkedTools.length > 0 ? linkedTools : input.tools.slice(0, 1);
        sources.forEach((tool)=>{
            edges.push(canvasEdge(`rca-tool-${tool.id}-${id}`, `rca-tool-${tool.id}`, id, tone, candidate.rank <= 3));
        });
        if (sources.length === 0) {
            edges.push(canvasEdge(`rca-investigation-${id}`, "rca-investigation", id, tone, candidate.rank <= 3));
        }
    });
    input.blockers.slice(0, 5).forEach((blocker, index)=>{
        const id = `rca-blocker-${blocker.id}`;
        const tone = blocker.severity === "danger" ? GRAPH_TONE.danger : GRAPH_TONE.warn;
        nodes.push(canvasNode({
            id,
            kind: "artifact",
            title: blocker.label,
            statusLabel: humanizeToken(blocker.source),
            preview: blocker.detail,
            accent: tone,
            meta: [],
            position: {
                x: 1000,
                y: 80 + index * 122
            },
            artifactKey: "evaluation"
        }));
        const candidate = input.candidates[index] ?? input.candidates[0];
        edges.push(canvasEdge(`rca-blocker-${index}`, candidate ? `rca-candidate-${candidate.id}` : "rca-investigation", id, tone, true));
    });
    input.citations.slice(0, 8).forEach((citation, index)=>{
        const id = `rca-citation-${citation.id}`;
        nodes.push(canvasNode({
            id,
            kind: "merkle",
            title: citation.label,
            statusLabel: "Citation",
            preview: citation.detail,
            accent: GRAPH_TONE.purple,
            meta: compact([
                citation.id
            ]),
            position: {
                x: 1300,
                y: 50 + index * 104
            },
            artifactKey: "investigation_report"
        }));
        const candidate = input.candidates.find((item)=>item.citationIds.includes(citation.id)) ?? input.candidates[0];
        const source = candidate ? `rca-candidate-${candidate.id}` : input.blockers[0] ? `rca-blocker-${input.blockers[0].id}` : "rca-investigation";
        edges.push(canvasEdge(`${source}-${id}`, source, id, GRAPH_TONE.purple, true));
    });
    return {
        nodes,
        edges
    };
}
function buildRethSignalGraph(signal) {
    if (!signal || signal.signal_type !== "reth_node") return {
        nodes: [],
        edges: []
    };
    const service = String(signal.service ?? signal.node?.name ?? "reth node");
    const executionTone = Number(signal.execution?.peer_count ?? 0) <= Number(signal.execution?.min_peer_count ?? -1) ? GRAPH_TONE.warn : GRAPH_TONE.success;
    const storageTone = Number(signal.storage?.disk_used_pct ?? 0) >= 90 ? GRAPH_TONE.danger : GRAPH_TONE.success;
    const consensusTone = signal.consensus?.engine_api_reachable === false ? GRAPH_TONE.danger : GRAPH_TONE.success;
    const rpcTone = signal.rpc?.http_reachable === false ? GRAPH_TONE.danger : GRAPH_TONE.info;
    const nodes = [
        canvasNode({
            id: "reth-service",
            kind: "kubernetes",
            title: service,
            statusLabel: String(signal.environment ?? "environment"),
            preview: `${signal.node?.client_version ?? signal.node?.network ?? "reth"} / ${signal.node?.deployment_mode ?? "node"}`,
            accent: GRAPH_TONE.info,
            meta: compact([
                signal.node?.role,
                signal.related_context?.kurtosis_enclave
            ]),
            position: {
                x: 40,
                y: 240
            },
            artifactKey: "input_signal"
        }),
        canvasNode({
            id: "reth-execution",
            kind: "kubernetes",
            title: "Execution",
            statusLabel: signal.execution?.syncing ? "Syncing" : "Head",
            preview: `head ${signal.execution?.head_block ?? "?"} / lag ${signal.execution?.block_lag ?? "?"}`,
            accent: executionTone,
            meta: compact([
                `peers:${signal.execution?.peer_count ?? "?"}`,
                `min:${signal.execution?.min_peer_count ?? "?"}`
            ]),
            position: {
                x: 330,
                y: 90
            },
            artifactKey: "input_signal"
        }),
        canvasNode({
            id: "reth-consensus",
            kind: "kubernetes",
            title: "Consensus",
            statusLabel: String(signal.consensus?.consensus_client ?? signal.consensus?.client_kind ?? "consensus"),
            preview: signal.consensus?.engine_api_reachable === false ? "Engine API unreachable" : "Engine API reachable",
            accent: consensusTone,
            meta: compact([
                signal.consensus?.client_kind,
                signal.consensus?.forkchoice_updates_recent ? "forkchoice recent" : undefined
            ]),
            position: {
                x: 330,
                y: 250
            },
            artifactKey: "input_signal"
        }),
        canvasNode({
            id: "reth-storage",
            kind: "kubernetes",
            title: "Storage",
            statusLabel: signal.storage?.disk_used_pct == null ? "Unknown" : `${signal.storage.disk_used_pct}% used`,
            preview: String(signal.storage?.diagnostic_source ?? signal.storage?.snapshot_mode ?? "storage"),
            accent: storageTone,
            meta: compact([
                signal.storage?.snapshot_mode,
                signal.storage?.data_dir_free_bytes != null ? `${signal.storage.data_dir_free_bytes} free` : undefined
            ]),
            position: {
                x: 630,
                y: 170
            },
            artifactKey: "input_signal"
        }),
        canvasNode({
            id: "reth-rpc",
            kind: "kubernetes",
            title: "RPC",
            statusLabel: signal.rpc?.http_reachable === false ? "Unreachable" : "Reachable",
            preview: `error rate ${signal.rpc?.error_rate ?? "?"} / latency ${signal.rpc?.latency_ms ?? "?"}`,
            accent: rpcTone,
            meta: compact([
                signal.rpc?.publicly_exposed ? "public" : "internal",
                signal.resource_attributes?.["mesh.node.rpc_url"]
            ]),
            position: {
                x: 930,
                y: 240
            },
            artifactKey: "input_signal"
        })
    ];
    const edges = [
        canvasEdge("reth-service-execution", "reth-service", "reth-execution", executionTone),
        canvasEdge("reth-service-consensus", "reth-service", "reth-consensus", consensusTone),
        canvasEdge("reth-execution-storage", "reth-execution", "reth-storage", storageTone, storageTone === GRAPH_TONE.danger),
        canvasEdge("reth-consensus-rpc", "reth-consensus", "reth-rpc", rpcTone, rpcTone === GRAPH_TONE.danger)
    ];
    return {
        nodes,
        edges
    };
}
function buildKubernetesGraph(signal) {
    if (!isKubernetesSignal(signal)) return {
        nodes: [],
        edges: []
    };
    const nodes = [];
    const edges = [];
    const deploymentTone = kubernetesTone(signal.deployment?.rollout_status);
    nodes.push(canvasNode({
        id: "cluster",
        kind: "kubernetes",
        title: String(signal.cluster ?? "cluster"),
        statusLabel: String(signal.environment ?? "cluster"),
        preview: `${signal.service ?? "service"} in ${signal.namespace ?? "default"}`,
        accent: GRAPH_TONE.info,
        meta: compact([
            signal.signal_type,
            signal.observed_at
        ]),
        position: {
            x: 40,
            y: 180
        },
        artifactKey: "input_signal"
    }));
    nodes.push(canvasNode({
        id: "namespace",
        kind: "kubernetes",
        title: String(signal.namespace ?? "default"),
        statusLabel: "Namespace",
        preview: `${signal.service ?? "service"} workload`,
        accent: GRAPH_TONE.active,
        meta: compact([
            `service:${signal.service ?? "unknown"}`
        ]),
        position: {
            x: 290,
            y: 180
        },
        artifactKey: "input_signal"
    }));
    nodes.push(canvasNode({
        id: "deployment",
        kind: "kubernetes",
        title: String(signal.deployment?.name ?? signal.service ?? "deployment"),
        statusLabel: humanizeToken(String(signal.deployment?.rollout_status ?? "unknown")),
        preview: `${signal.deployment?.available_replicas ?? 0}/${signal.deployment?.desired_replicas ?? 0} replicas available`,
        accent: deploymentTone,
        meta: compact([
            `rev:${signal.deployment?.revision ?? "?"}`,
            signal.deployment?.image ? truncateInline(String(signal.deployment.image), 26) : undefined
        ]),
        position: {
            x: 560,
            y: 180
        },
        artifactKey: "input_signal"
    }));
    edges.push(canvasEdge("cluster-namespace", "cluster", "namespace", GRAPH_TONE.info));
    edges.push(canvasEdge("namespace-deployment", "namespace", "deployment", deploymentTone));
    (signal.pods ?? []).slice(0, 6).forEach((pod, index)=>{
        const tone = pod.ready ? GRAPH_TONE.success : GRAPH_TONE.danger;
        const podId = `pod-${index}`;
        nodes.push(canvasNode({
            id: podId,
            kind: "kubernetes",
            title: String(pod.name ?? `pod-${index + 1}`),
            statusLabel: pod.ready ? "Ready" : String(pod.container_status ?? pod.phase ?? "Unready"),
            preview: `${pod.phase ?? "Unknown"} • ${pod.restarts ?? 0} restarts`,
            accent: tone,
            meta: compact([
                pod.last_state_reason ? String(pod.last_state_reason) : undefined,
                pod.container_status ? String(pod.container_status) : undefined
            ]),
            position: {
                x: 880,
                y: 60 + index * 116
            },
            artifactKey: "input_signal"
        }));
        edges.push(canvasEdge(`deployment-${podId}`, "deployment", podId, tone));
    });
    (signal.events ?? []).slice(0, 4).forEach((event, index)=>{
        const tone = String(event.type ?? "").toLowerCase() === "warning" ? GRAPH_TONE.warn : GRAPH_TONE.info;
        const eventId = `cluster-event-${index}`;
        nodes.push(canvasNode({
            id: eventId,
            kind: "kubernetes",
            title: String(event.reason ?? `Event ${index + 1}`),
            statusLabel: String(event.type ?? "Event"),
            preview: truncateInline(String(event.message ?? "No message"), 64),
            accent: tone,
            meta: compact([
                event.count != null ? `count:${event.count}` : undefined
            ]),
            position: {
                x: 1170,
                y: 110 + index * 116
            },
            artifactKey: "input_signal"
        }));
        edges.push(canvasEdge(`deployment-${eventId}`, "deployment", eventId, tone, true));
    });
    return {
        nodes,
        edges
    };
}
function buildMerkleGraph(snapshot, proof) {
    if (!snapshot?.root_hash) return {
        nodes: [],
        edges: []
    };
    const nodes = [];
    const edges = [];
    const centerX = 560;
    nodes.push(canvasNode({
        id: "merkle-root",
        kind: "merkle",
        title: "Merkle Root",
        statusLabel: proof?.valid ? "Verified" : "Snapshot",
        preview: snapshot.root_hash,
        accent: proof?.valid ? GRAPH_TONE.success : GRAPH_TONE.info,
        meta: compact([
            `${snapshot.leaf_count} leaves`
        ]),
        position: {
            x: centerX,
            y: 20
        },
        eventId: proof?.event_id
    }));
    nodes.push(canvasNode({
        id: "merkle-snapshot",
        kind: "merkle",
        title: "Snapshot",
        statusLabel: "Ledger",
        preview: `${snapshot.event_ids.length} event ids tracked`,
        accent: GRAPH_TONE.active,
        meta: compact([
            snapshot.event_ids[0],
            snapshot.event_ids[snapshot.event_ids.length - 1]
        ]),
        position: {
            x: 180,
            y: 20
        },
        eventId: proof?.event_id
    }));
    edges.push(canvasEdge("merkle-snapshot-root", "merkle-snapshot", "merkle-root", GRAPH_TONE.active));
    let previousId = "merkle-root";
    proof?.proof.forEach((step, index)=>{
        const stepId = `merkle-step-${index}`;
        const siblingId = `merkle-sibling-${index}`;
        const tone = step.position === "left" ? GRAPH_TONE.info : GRAPH_TONE.warn;
        const y = 150 + index * 132;
        nodes.push(canvasNode({
            id: stepId,
            kind: "merkle",
            title: `Proof Step ${index + 1}`,
            statusLabel: "Branch",
            preview: `combine ${step.position} sibling`,
            accent: GRAPH_TONE.active,
            meta: compact([
                proof?.event_id ?? undefined
            ]),
            position: {
                x: centerX,
                y
            },
            eventId: proof?.event_id
        }));
        nodes.push(canvasNode({
            id: siblingId,
            kind: "merkle",
            title: `Sibling ${index + 1}`,
            statusLabel: humanizeToken(step.position),
            preview: step.hash,
            accent: tone,
            meta: [],
            position: {
                x: step.position === "left" ? centerX - 280 : centerX + 280,
                y
            },
            eventId: proof?.event_id
        }));
        edges.push(canvasEdge(`${previousId}-${stepId}`, previousId, stepId, GRAPH_TONE.active));
        edges.push(canvasEdge(`${siblingId}-${stepId}`, siblingId, stepId, tone, true));
        previousId = stepId;
    });
    if (proof?.leaf_hash) {
        nodes.push(canvasNode({
            id: "merkle-leaf",
            kind: "merkle",
            title: "Selected Leaf",
            statusLabel: proof.event_id,
            preview: proof.leaf_hash,
            accent: GRAPH_TONE.success,
            meta: compact([
                proof.event_id
            ]),
            position: {
                x: centerX,
                y: 170 + (proof.proof.length + 1) * 132
            },
            eventId: proof.event_id
        }));
        edges.push(canvasEdge(`${previousId}-merkle-leaf`, previousId, "merkle-leaf", GRAPH_TONE.success));
    }
    return {
        nodes,
        edges
    };
}
function buildArtifactGraph(run) {
    if (!run) return {
        nodes: [],
        edges: []
    };
    const orderedArtifacts = [
        [
            "input_signal",
            "Input Signal",
            GRAPH_TONE.info
        ],
        [
            "integration_readiness",
            "Readiness",
            GRAPH_TONE.active
        ],
        [
            "normalized_event",
            "Normalized Event",
            GRAPH_TONE.purple
        ],
        [
            "trigger",
            "Trigger",
            GRAPH_TONE.info
        ],
        [
            "investigation_report",
            "Investigation",
            GRAPH_TONE.active
        ],
        [
            "tool_trajectory",
            "Tool Trajectory",
            GRAPH_TONE.active
        ],
        [
            "decision",
            "Decision",
            GRAPH_TONE.info
        ],
        [
            "evaluation",
            "Evaluation",
            GRAPH_TONE.warn
        ],
        [
            "task_trace",
            "Task Trace",
            GRAPH_TONE.warn
        ],
        [
            "trajectory_score",
            "Trajectory Score",
            GRAPH_TONE.warn
        ],
        [
            "verifier_output",
            "Verifier Output",
            GRAPH_TONE.warn
        ],
        [
            "phoenix_spans",
            "Phoenix Spans",
            GRAPH_TONE.warn
        ],
        [
            "hermes_explanation",
            "Hermes Explanation",
            GRAPH_TONE.functionBlue
        ],
        [
            "execution",
            "Execution",
            GRAPH_TONE.active
        ],
        [
            "goose_review",
            "Goose Review",
            GRAPH_TONE.cyan
        ],
        [
            "hermes_review",
            "Hermes Review",
            GRAPH_TONE.functionBlue
        ],
        [
            "feedback",
            "Feedback",
            GRAPH_TONE.success
        ]
    ];
    const nodes = [];
    const edges = [];
    let previousId = null;
    orderedArtifacts.forEach(([key, label, accent], index)=>{
        const artifact = run.artifacts?.[key];
        if (!artifact) return;
        const nodeId = `artifact-${key}`;
        nodes.push(canvasNode({
            id: nodeId,
            kind: "artifact",
            title: label,
            statusLabel: artifact.status ? humanizeToken(String(artifact.status)) : humanizeToken(key),
            preview: summarizeArtifact(artifact),
            accent,
            meta: compact([
                artifact.decision_type ? humanizeToken(String(artifact.decision_type)) : undefined,
                artifact.final_recommendation ? humanizeToken(String(artifact.final_recommendation)) : undefined,
                artifact.executor ? humanizeToken(String(artifact.executor)) : undefined
            ]),
            position: {
                x: 110 + index * 248,
                y: 170 + (index % 2 === 0 ? 0 : 78)
            },
            artifactKey: key
        }));
        if (previousId) {
            edges.push(canvasEdge(`${previousId}-${nodeId}`, previousId, nodeId, accent));
        }
        previousId = nodeId;
    });
    if (nodes.length > 0) {
        nodes.unshift(canvasNode({
            id: "artifact-run",
            kind: "artifact",
            title: "Run Session",
            statusLabel: humanizeToken(run.stage),
            preview: `session ${humanizeToken(run.status)}`,
            accent: toneForStage(run.stage),
            meta: [],
            position: {
                x: 20,
                y: 170
            },
            artifactKey: "run_session"
        }));
        edges.unshift(canvasEdge("artifact-run-first", "artifact-run", nodes[1].id, toneForStage(run.stage)));
    }
    return {
        nodes,
        edges
    };
}
function buildUnifiedGraph(graphs) {
    const flow = namespaceGraph(graphs.flow, "flow", {
        x: 0,
        y: 0
    });
    const flowBounds = graphBounds(flow.nodes);
    const lowerY = flow.nodes.length > 0 ? flowBounds.maxY + 260 : 0;
    const kubernetes = namespaceGraph(graphs.kubernetes, "kubernetes", {
        x: 0,
        y: lowerY
    });
    const kubernetesBounds = graphBounds(kubernetes.nodes);
    const merkleX = kubernetes.nodes.length > 0 ? Math.max(kubernetesBounds.maxX + 360, 920) : 0;
    const merkle = namespaceGraph(graphs.merkle, "merkle", {
        x: merkleX,
        y: lowerY
    });
    const merkleBounds = graphBounds(merkle.nodes);
    const artifactY = Math.max(kubernetesBounds.maxY, merkleBounds.maxY, lowerY) + 260;
    const artifacts = namespaceGraph(graphs.artifacts, "artifacts", {
        x: 0,
        y: artifactY
    });
    const nodes = [
        ...unifiedSectionNodes([
            {
                graph: flow,
                id: "flow",
                title: "Run Flow",
                preview: "Stage-by-stage run event timeline",
                accent: GRAPH_TONE.info
            },
            {
                graph: kubernetes,
                id: "kubernetes",
                title: "Kubernetes",
                preview: "Cluster, namespace, deployment, pods, and events",
                accent: GRAPH_TONE.active
            },
            {
                graph: merkle,
                id: "merkle",
                title: "Merkle",
                preview: "Run log root, snapshot, and proof material",
                accent: GRAPH_TONE.purple
            },
            {
                graph: artifacts,
                id: "artifacts",
                title: "Artifacts",
                preview: "Input, readiness, trigger, decision, execution, and feedback records",
                accent: GRAPH_TONE.warn
            }
        ]),
        ...flow.nodes,
        ...kubernetes.nodes,
        ...merkle.nodes,
        ...artifacts.nodes
    ];
    const edges = [
        ...flow.edges,
        ...kubernetes.edges,
        ...merkle.edges,
        ...artifacts.edges,
        ...unifiedContextEdges(flow, kubernetes, merkle, artifacts)
    ];
    return {
        nodes,
        edges
    };
}
function toneForStage(stage) {
    if (stage === "completed") return GRAPH_TONE.success;
    if (stage === "failed" || stage === "cancelled") return GRAPH_TONE.danger;
    if (stage === "awaiting_operator") return GRAPH_TONE.warn;
    if (stage === "executing") return GRAPH_TONE.active;
    if (stage === "evaluation_ready" || stage === "decision_ready" || stage === "scenario_analysis_ready" || stage === "investigation_ready") return GRAPH_TONE.info;
    return GRAPH_TONE.neutral;
}
function summarizeEvent(event) {
    const summaryEntries = event.summary ? Object.entries(event.summary) : [];
    for (const [, value] of summaryEntries){
        const preview = stringifyValue(value);
        if (preview) return preview;
    }
    const payloadEntries = Object.entries(event.payload ?? {});
    for (const [, value] of payloadEntries){
        const preview = stringifyValue(value);
        if (preview) return preview;
    }
    if (event.integration_name) return event.integration_name;
    if (event.artifact_key) return event.artifact_key;
    return event.recorded_at;
}
function stringifyValue(value) {
    if (value == null) return "";
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    if (Array.isArray(value)) return value.length === 0 ? "" : `${value.length} items`;
    if (typeof value === "object") return `${Object.keys(value).length} fields`;
    return "";
}
function canvasNode({ id, kind, title, statusLabel, preview, accent, meta, position, eventId, sequence, eventType, stage, recordedAt, integrationName, artifactKey }, selected = false) {
    return {
        id,
        type: "runEvent",
        selected,
        data: {
            nodeKind: kind,
            title,
            statusLabel,
            accent,
            meta,
            eventId: eventId ?? "",
            sequence: sequence ?? 0,
            eventType: eventType ?? title,
            stage: stage ?? statusLabel,
            recordedAt: recordedAt ?? "",
            preview,
            integrationName,
            artifactKey
        },
        position,
        sourcePosition: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f40$xyflow$2b$system$40$0$2e$0$2e$76$2f$node_modules$2f40$xyflow$2f$system$2f$dist$2f$esm$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["Position"].Right,
        targetPosition: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f40$xyflow$2b$system$40$0$2e$0$2e$76$2f$node_modules$2f40$xyflow$2f$system$2f$dist$2f$esm$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["Position"].Left,
        style: {
            width: selected ? 220 : 204
        }
    };
}
function canvasEdge(id, source, target, stroke, animated = false) {
    return {
        id,
        source,
        target,
        type: "smoothstep",
        animated,
        style: {
            stroke,
            strokeWidth: 1.6,
            opacity: 0.82
        }
    };
}
function namespaceGraph(graph, prefix, offset) {
    return {
        nodes: graph.nodes.map((node)=>({
                ...node,
                id: `${prefix}:${node.id}`,
                position: {
                    x: node.position.x + offset.x,
                    y: node.position.y + offset.y
                }
            })),
        edges: graph.edges.map((edge)=>({
                ...edge,
                id: `${prefix}:${edge.id}`,
                source: `${prefix}:${edge.source}`,
                target: `${prefix}:${edge.target}`
            }))
    };
}
function unifiedSectionNodes(sections) {
    return sections.filter((section)=>section.graph.nodes.length > 0).map((section)=>{
        const firstNode = section.graph.nodes[0];
        return canvasNode({
            id: `section:${section.id}`,
            kind: "section",
            title: section.title,
            statusLabel: "Unified Section",
            preview: section.preview,
            accent: section.accent,
            meta: compact([
                `${section.graph.nodes.length} nodes`
            ]),
            position: {
                x: firstNode.position.x,
                y: firstNode.position.y - 150
            }
        });
    });
}
function graphBounds(nodes) {
    if (nodes.length === 0) return {
        maxX: 0,
        maxY: 0
    };
    return nodes.reduce((bounds, node)=>({
            maxX: Math.max(bounds.maxX, node.position.x + Number(node.style?.width ?? 204)),
            maxY: Math.max(bounds.maxY, node.position.y + 110)
        }), {
        maxX: 0,
        maxY: 0
    });
}
function unifiedContextEdges(flow, kubernetes, merkle, artifacts) {
    const edges = [];
    const nodeIds = new Set([
        ...flow.nodes,
        ...kubernetes.nodes,
        ...merkle.nodes,
        ...artifacts.nodes
    ].map((node)=>node.id));
    const artifactByKey = new Map();
    artifacts.nodes.forEach((node)=>{
        const key = node.data.artifactKey;
        if (typeof key === "string" && key) artifactByKey.set(key, node.id);
    });
    flow.nodes.forEach((node)=>{
        const key = node.data.artifactKey;
        if (typeof key !== "string" || !key) return;
        const artifactNodeId = artifactByKey.get(key);
        if (!artifactNodeId) return;
        edges.push(canvasEdge(`unified:${node.id}-${artifactNodeId}`, node.id, artifactNodeId, String(node.data.accent || GRAPH_TONE.info), true));
    });
    const inputSignalNodeId = artifactByKey.get("input_signal");
    if (inputSignalNodeId && nodeIds.has("kubernetes:cluster")) {
        edges.push(canvasEdge("unified:input-signal-kubernetes", inputSignalNodeId, "kubernetes:cluster", GRAPH_TONE.info, true));
    }
    const executionNodeId = artifactByKey.get("execution");
    if (executionNodeId && nodeIds.has("merkle:merkle-root")) {
        edges.push(canvasEdge("unified:execution-merkle-root", executionNodeId, "merkle:merkle-root", GRAPH_TONE.active, true));
    } else if (flow.nodes.length > 0 && nodeIds.has("merkle:merkle-root")) {
        edges.push(canvasEdge("unified:flow-merkle-root", flow.nodes[flow.nodes.length - 1].id, "merkle:merkle-root", GRAPH_TONE.active, true));
    }
    return edges;
}
function kubernetesTone(rolloutStatus) {
    if (rolloutStatus === "healthy") return GRAPH_TONE.success;
    if (rolloutStatus === "degraded" || rolloutStatus === "failed") return GRAPH_TONE.danger;
    return GRAPH_TONE.info;
}
function isKubernetesSignal(signal) {
    return Boolean(signal && signal.signal_type === "kubernetes_deployment_issue" && signal.deployment);
}
function summarizeArtifact(artifact) {
    const keys = [
        "summary",
        "decision_type",
        "final_recommendation",
        "status",
        "outcome"
    ];
    for (const key of keys){
        const value = artifact?.[key];
        const preview = stringifyValue(value);
        if (preview) return preview;
    }
    return `${Object.keys(artifact ?? {}).length} fields`;
}
function compact(values) {
    return values.filter((value)=>Boolean(value && value.trim()));
}
function truncateInline(value, max = 36) {
    if (value.length <= max) return value;
    return `${value.slice(0, max - 1)}…`;
}
function humanizeToken(value) {
    return value.replace(/_/g, " ").replace(/\b\w/g, (char)=>char.toUpperCase());
}
function toneForSeverity(severity) {
    if (severity === "danger") return GRAPH_TONE.danger;
    if (severity === "warning") return GRAPH_TONE.warn;
    if (severity === "success") return GRAPH_TONE.success;
    return GRAPH_TONE.info;
}
if (typeof globalThis.$RefreshHelpers$ === 'object' && globalThis.$RefreshHelpers !== null) {
    __turbopack_context__.k.registerExports(__turbopack_context__.m, globalThis.$RefreshHelpers$);
}
}),
]);

//# sourceMappingURL=src_0d.gbk6._.js.map