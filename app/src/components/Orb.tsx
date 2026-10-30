import type { AssistantState } from "@protocol/ipc";

// Placeholder look until WP14 designs Solana's own character.
const looks: Record<AssistantState, { core: string; glow: string; motion: string }> = {
  idle: {
    core: "from-amber-300 via-orange-400 to-rose-500",
    glow: "bg-orange-500/30",
    motion: "animate-breathe",
  },
  wake: {
    core: "from-yellow-200 via-amber-300 to-orange-500",
    glow: "bg-amber-400/50",
    motion: "scale-110",
  },
  listening: {
    core: "from-cyan-200 via-sky-400 to-indigo-500",
    glow: "bg-sky-400/40",
    motion: "animate-pulse-fast",
  },
  thinking: {
    core: "from-violet-300 via-fuchsia-500 to-indigo-600",
    glow: "bg-fuchsia-500/40",
    motion: "animate-spin-slow",
  },
  speaking: {
    core: "from-amber-200 via-orange-400 to-pink-500",
    glow: "bg-orange-400/50",
    motion: "animate-pulse-fast",
  },
  muted: {
    core: "from-slate-500 via-slate-600 to-slate-700",
    glow: "bg-slate-500/10",
    motion: "",
  },
  error: { core: "from-red-400 via-red-500 to-red-700", glow: "bg-red-500/40", motion: "" },
};

const sizes = {
  lg: {
    box: "size-56",
    glow: "inset-6 blur-3xl",
    ring: "inset-10",
    core: "size-36",
    shine: "inset-3",
  },
  md: {
    box: "size-24",
    glow: "inset-2 blur-2xl",
    ring: "inset-4",
    core: "size-14",
    shine: "inset-1.5",
  },
  sm: {
    box: "size-12",
    glow: "inset-1 blur-lg",
    ring: "inset-2",
    core: "size-8",
    shine: "inset-1",
  },
};

export function Orb({ state, size = "lg" }: { state: AssistantState; size?: keyof typeof sizes }) {
  const look = looks[state];
  const dims = sizes[size];
  return (
    <div
      className={`relative flex shrink-0 items-center justify-center ${dims.box}`}
      data-state={state}
    >
      <div className={`absolute rounded-full transition-colors ${dims.glow} ${look.glow}`} />
      {state === "listening" && (
        <div
          className={`animate-ring absolute rounded-full border-2 border-sky-300/60 ${dims.ring}`}
        />
      )}
      <div
        className={`relative rounded-full bg-gradient-to-br shadow-2xl transition-all duration-500 ${dims.core} ${look.core} ${look.motion}`}
      >
        <div
          className={`absolute rounded-full bg-gradient-to-tl from-white/0 to-white/40 ${dims.shine}`}
        />
      </div>
    </div>
  );
}
