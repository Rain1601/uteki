/**
 * /icon-lab — a design board for picking the uteki favicon.
 *
 * Each variant is rendered at the actual sizes the browser uses for favicons
 * (16 → 192 px) on both dark + light backgrounds so the user can see how it
 * survives across tab, dock, light mode, dark mode, etc.
 *
 * Not auth-gated — it's a local design tool, kept out of the (app) group so
 * it doesn't inherit the sidebar chrome.
 */
"use client";

import { useState } from "react";

type VariantId = "A" | "B" | "C" | "D" | "E" | "F" | "G" | "H" | "I" | "J";

interface Variant {
  id: VariantId;
  title: string;
  blurb: string;
  svg: React.ReactNode;
}

const VARIANTS: Variant[] = [
  {
    id: "A",
    title: "纯实色雨滴",
    blurb: "最干净。锐顶宽底标准 raindrop，单色赤陶。Anthropic 极简思路。",
    svg: (
      <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
        <path
          d="M32 6 C 32 24, 53 32, 52 44 C 52 55, 43 60, 32 60 C 21 60, 12 55, 12 44 C 11 32, 32 24, 32 6 Z"
          fill="#d97757"
        />
      </svg>
    ),
  },
  {
    id: "B",
    title: "实色 + 小高光",
    blurb: "实色 + 左上一颗椭圆小亮点，更像「湿润 / 真实」。",
    svg: (
      <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
        <path
          d="M32 6 C 32 24, 53 32, 52 44 C 52 55, 43 60, 32 60 C 21 60, 12 55, 12 44 C 11 32, 32 24, 32 6 Z"
          fill="#d97757"
        />
        <ellipse cx="24" cy="38" rx="3" ry="6" fill="rgba(255,255,255,0.55)" />
      </svg>
    ),
  },
  {
    id: "C",
    title: "两滴重叠（uteki = 重复数据点）",
    blurb: "两颗叠放，一深一浅。讲「重复数据 / 多次观察」故事。",
    svg: (
      <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
        <path
          d="M22 4 C 22 18, 35 22, 35 32 C 35 39, 29 43, 22 43 C 15 43, 9 39, 9 32 C 9 22, 22 18, 22 4 Z"
          fill="#d97757"
        />
        <path
          d="M42 22 C 42 36, 56 40, 56 50 C 56 57, 50 61, 42 61 C 35 61, 28 57, 29 50 C 29 40, 42 36, 42 22 Z"
          fill="#c75a3a"
          opacity="0.9"
        />
      </svg>
    ),
  },
  {
    id: "D",
    title: "雨滴 + 涟漪",
    blurb: "雨滴下方一条小弧线表示落入水面。投研「分析 / 涟漪」隐喻最贴切。",
    svg: (
      <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
        <path
          d="M32 4 C 32 22, 49 30, 49 41 C 49 50, 41 55, 32 55 C 23 55, 15 50, 15 41 C 15 30, 32 22, 32 4 Z"
          fill="#d97757"
        />
        <path
          d="M14 58 C 22 53, 42 53, 50 58"
          stroke="#d97757"
          strokeWidth="3"
          fill="none"
          strokeLinecap="round"
          opacity="0.7"
        />
      </svg>
    ),
  },
  {
    id: "E",
    title: "Candlestick 烛台（换方向）",
    blurb: "3 根 K 线，赤陶 + 奶白。直白的金融/投研符号，零模糊。",
    svg: (
      <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
        {/* upper wicks */}
        <path d="M16 12 L16 22" stroke="rgba(255,255,255,0.92)" strokeWidth="3" strokeLinecap="round" />
        <path d="M32 8 L32 18" stroke="rgba(255,255,255,0.92)" strokeWidth="3" strokeLinecap="round" />
        <path d="M48 16 L48 24" stroke="rgba(255,255,255,0.92)" strokeWidth="3" strokeLinecap="round" />
        {/* bodies */}
        <path d="M11 22 L21 22 L21 44 L11 44 Z" fill="#d97757" />
        <path d="M27 18 L37 18 L37 50 L27 50 Z" fill="#d97757" />
        <path
          d="M43 24 L53 24 L53 42 L43 42 Z"
          fill="none"
          stroke="#d97757"
          strokeWidth="3"
          strokeLinejoin="round"
        />
        {/* lower wicks */}
        <path d="M16 44 L16 54" stroke="rgba(255,255,255,0.92)" strokeWidth="3" strokeLinecap="round" />
        <path d="M32 50 L32 58" stroke="rgba(255,255,255,0.92)" strokeWidth="3" strokeLinecap="round" />
        <path d="M48 42 L48 50" stroke="rgba(255,255,255,0.92)" strokeWidth="3" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: "F",
    title: '抽象 "u" — 杯型字符',
    blurb: '小写 "u" 用杯型曲线表达，下面一颗赤陶水滴落进杯里。',
    svg: (
      <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
        {/* u shape — cream stroke cup */}
        <path
          d="M14 14 L14 38 C 14 50, 22 56, 32 56 C 42 56, 50 50, 50 38 L50 14"
          fill="none"
          stroke="rgba(255,255,255,0.92)"
          strokeWidth="6"
          strokeLinecap="round"
        />
        {/* tiny terracotta drop in the cup */}
        <path
          d="M32 26 C 32 32, 38 35, 38 40 C 38 43, 35 45, 32 45 C 29 45, 26 43, 26 40 C 26 35, 32 32, 32 26 Z"
          fill="#d97757"
        />
      </svg>
    ),
  },

  // ── 更多设计元素 / 动态系列 ─────────────────────────────────────────────

  {
    id: "G",
    title: "雨滴 + Anthropic 签名 squiggle",
    blurb:
      "上面赤陶雨滴，下方一条厚奶白手绘 squiggle + 小回环 + 端点小陶点。SKILL.md 里 Anthropic 的标志性「hand motif」，带手写温度。",
    svg: (
      <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
        {/* main raindrop */}
        <path
          d="M32 5 C 32 20, 47 28, 46 38 C 46 46, 39 50, 32 50 C 25 50, 18 46, 18 38 C 18 28, 32 20, 32 5 Z"
          fill="#d97757"
        />
        {/* signature squiggle — thick marker, gently wavy with a small loop */}
        <path
          d="M10 56 C 16 50, 22 60, 30 54 C 36 50, 42 60, 48 54"
          fill="none"
          stroke="rgba(255,255,255,0.92)"
          strokeWidth="4"
          strokeLinecap="round"
        />
        {/* end loop */}
        <path
          d="M48 54 C 54 52, 56 58, 52 60"
          fill="none"
          stroke="rgba(255,255,255,0.88)"
          strokeWidth="3.5"
          strokeLinecap="round"
        />
        {/* tiny terracotta dot at the loop junction */}
        <circle cx="52" cy="58" r="1.8" fill="#d97757" />
      </svg>
    ),
  },

  {
    id: "H",
    title: "雨滴落地 + 飞溅 splash crown",
    blurb:
      "雨滴砸进水面瞬间 — 主滴下方两侧飞溅出小水珠（皇冠形），底部是溅起的水面线。最动态的一个，最像「落地碰撞」。",
    svg: (
      <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
        {/* main raindrop — slightly squashed (just impacted) */}
        <path
          d="M32 6 C 32 18, 46 24, 46 33 C 46 41, 39 45, 32 45 C 25 45, 18 41, 18 33 C 18 24, 32 18, 32 6 Z"
          fill="#d97757"
        />
        {/* splash droplets — fanning out from impact zone */}
        <ellipse cx="12" cy="50" rx="2.5" ry="3.5" fill="#d97757" />
        <ellipse cx="20" cy="54" rx="2" ry="2.8" fill="#d97757" />
        <ellipse cx="44" cy="54" rx="2" ry="2.8" fill="#d97757" />
        <ellipse cx="52" cy="50" rx="2.5" ry="3.5" fill="#d97757" />
        {/* trailing curve droplets — diagonal motion */}
        <circle cx="8" cy="56" r="1.5" fill="#d97757" opacity="0.7" />
        <circle cx="56" cy="56" r="1.5" fill="#d97757" opacity="0.7" />
        {/* water surface line — cream curve, the moment of impact */}
        <path
          d="M6 58 Q 32 53, 58 58"
          fill="none"
          stroke="rgba(255,255,255,0.85)"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
    ),
  },

  {
    id: "I",
    title: "雨滴 + 三层涟漪环",
    blurb:
      "雨滴静态落入水面，下方三道扩散涟漪（从近到远逐渐变细变淡）。分析 / 影响力扩散的隐喻。",
    svg: (
      <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
        {/* main raindrop */}
        <path
          d="M32 4 C 32 18, 47 25, 46 35 C 46 43, 39 47, 32 47 C 25 47, 18 43, 18 35 C 18 25, 32 18, 32 4 Z"
          fill="#d97757"
        />
        {/* ripple 1 — closest, thickest */}
        <path
          d="M14 52 Q 32 47, 50 52"
          fill="none"
          stroke="rgba(255,255,255,0.92)"
          strokeWidth="3"
          strokeLinecap="round"
        />
        {/* ripple 2 — wider, thinner */}
        <path
          d="M8 57 Q 32 52, 56 57"
          fill="none"
          stroke="rgba(255,255,255,0.7)"
          strokeWidth="2.2"
          strokeLinecap="round"
        />
        {/* ripple 3 — outermost, faint */}
        <path
          d="M4 61 Q 32 57, 60 61"
          fill="none"
          stroke="rgba(255,255,255,0.45)"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      </svg>
    ),
  },

  {
    id: "J",
    title: "雨滴 + 倒影",
    blurb:
      "上下镜像 — 上方一颗实心赤陶雨滴，下方水面反射出半透明倒影，中间一条水面线分隔。安静、有诗意。",
    svg: (
      <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
        {/* main raindrop — upper half */}
        <path
          d="M32 6 C 32 17, 44 23, 44 30 C 44 36, 39 39, 32 39 C 25 39, 20 36, 20 30 C 20 23, 32 17, 32 6 Z"
          fill="#d97757"
        />
        {/* water surface line — cream, divides scene */}
        <path
          d="M6 42 L58 42"
          stroke="rgba(255,255,255,0.7)"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
        {/* reflection — mirrored droplet, faded */}
        <path
          d="M32 58 C 32 47, 44 41, 44 34 C 44 28, 39 25, 32 25 C 25 25, 20 28, 20 34 C 20 41, 32 47, 32 58 Z"
          fill="#d97757"
          opacity="0.32"
        />
      </svg>
    ),
  },
];

const SIZES = [16, 24, 32, 48, 64, 128];

export default function IconLabPage() {
  const [selected, setSelected] = useState<VariantId>("A");

  return (
    <div className="min-h-screen bg-[#1a1816] px-10 py-12 font-mono text-[13px] text-[#e8e0d6]">
      <header className="mb-10 max-w-3xl">
        <div className="mb-2 font-mono text-[10px] tracking-[0.2em] text-[#8a847c]">UTEKI · ICON LAB</div>
        <h1 className="mb-3 font-display text-[28px] italic text-[#fafaf7]">favicon variants</h1>
        <p className="leading-7 text-[#aaa39a]">
          每个 variant 在 16 / 24 / 32 / 48 / 64 / 128 px 都渲染一遍，深底 + 浅底各一行。
          选中后下方会显示 SVG 源码，告诉我哪个就 ship 哪个。
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        {VARIANTS.map((v) => (
          <button
            key={v.id}
            type="button"
            onClick={() => setSelected(v.id)}
            className={`border bg-[#211e1b] p-6 text-left transition-colors ${
              selected === v.id
                ? "border-[#d97757] bg-[#262320]"
                : "border-[#3a3530] hover:border-[#5a5048]"
            }`}
          >
            <div className="mb-3 flex items-baseline justify-between">
              <div className="flex items-baseline gap-3">
                <span
                  className={`font-display text-[22px] italic ${
                    selected === v.id ? "text-[#d97757]" : "text-[#fafaf7]"
                  }`}
                >
                  Variant {v.id}
                </span>
                <span className="text-[13px] text-[#aaa39a]">{v.title}</span>
              </div>
              {selected === v.id && (
                <span className="text-[10px] uppercase tracking-[0.18em] text-[#d97757]">selected</span>
              )}
            </div>
            <p className="mb-5 text-[12px] leading-6 text-[#888178]">{v.blurb}</p>

            {/* dark bg sample row */}
            <div className="mb-3 flex items-center gap-5 rounded-sm bg-[#0d0c0b] px-4 py-4">
              {SIZES.map((s) => (
                <div key={s} className="flex flex-col items-center gap-1.5">
                  <div style={{ width: s, height: s }}>{v.svg}</div>
                  <span className="text-[9px] text-[#555049]">{s}</span>
                </div>
              ))}
            </div>

            {/* light bg sample row */}
            <div className="flex items-center gap-5 rounded-sm bg-[#fafaf7] px-4 py-4">
              {SIZES.map((s) => (
                <div key={s} className="flex flex-col items-center gap-1.5">
                  <div style={{ width: s, height: s }}>{v.svg}</div>
                  <span className="text-[9px] text-[#999]">{s}</span>
                </div>
              ))}
            </div>

            {/* simulated browser tab row */}
            <div className="mt-3 flex items-center gap-3 rounded-t-md bg-[#2f2c2a] px-3 py-2 text-[11px] text-[#cfc8be]">
              <div style={{ width: 16, height: 16 }}>{v.svg}</div>
              <span className="font-mono">uteki — investment agent</span>
              <span className="ml-auto text-[#666]">localhost:3000</span>
            </div>
          </button>
        ))}
      </div>

      <div className="mt-12 border-t border-[#3a3530] pt-8">
        <div className="mb-2 font-mono text-[10px] tracking-[0.18em] text-[#8a847c]">SELECTED</div>
        <div className="mb-1 font-display text-[22px] italic text-[#d97757]">
          Variant {selected} — {VARIANTS.find((v) => v.id === selected)?.title}
        </div>
        <p className="text-[12px] text-[#aaa39a]">
          告诉我"用 {selected}"我就把 <code className="text-[#d97757]">app/icon.svg</code> + <code className="text-[#d97757]">app/apple-icon.svg</code> 替换成它，然后强刷浏览器就能看到了。
        </p>
      </div>
    </div>
  );
}
