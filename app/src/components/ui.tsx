// Small set of styled controls shared by the windows.
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from "react";

type Variant = "primary" | "ghost" | "danger" | "subtle";

const buttonLooks: Record<Variant, string> = {
  primary:
    "bg-gradient-to-br from-amber-300 to-orange-500 text-slate-950 shadow-lg shadow-orange-500/20 hover:brightness-110",
  ghost: "bg-white/5 text-slate-100 hover:bg-white/10 ring-1 ring-white/10",
  subtle: "text-slate-300 hover:bg-white/5 hover:text-slate-100",
  danger: "bg-rose-500/15 text-rose-200 ring-1 ring-rose-400/30 hover:bg-rose-500/25",
};

export function Button({
  variant = "ghost",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition disabled:pointer-events-none disabled:opacity-40 ${buttonLooks[variant]} ${className}`}
      {...props}
    />
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-40 ${
        checked ? "bg-gradient-to-r from-amber-400 to-orange-500" : "bg-white/15"
      }`}
    >
      <span
        className={`absolute top-0.5 left-0.5 size-5 rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-5" : ""
        }`}
      />
    </button>
  );
}

const fieldLook =
  "rounded-xl bg-slate-900/80 px-3 py-2 text-sm text-slate-100 ring-1 ring-white/10 outline-none transition focus:ring-2 focus:ring-amber-400/60 disabled:opacity-50";

export function Select({ className = "", ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={`${fieldLook} ${className}`} {...props} />;
}

export function TextField({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`${fieldLook} ${className}`} {...props} />;
}

export function Slider({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input type="range" className={`w-40 accent-orange-400 ${className}`} {...props} />;
}

export function Row({
  label,
  hint,
  children,
}: {
  label: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-6 border-b border-white/5 py-3.5 last:border-0">
      <div className="min-w-0">
        <div className="text-sm font-medium text-slate-100">{label}</div>
        {hint && <div className="mt-0.5 text-xs text-slate-400">{hint}</div>}
      </div>
      <div className="flex shrink-0 items-center gap-2">{children}</div>
    </div>
  );
}

export function Section({ title, children }: { title?: ReactNode; children: ReactNode }) {
  return (
    <section className="mb-5">
      {title && (
        <h3 className="mb-2 text-xs font-semibold tracking-wider text-slate-400 uppercase">
          {title}
        </h3>
      )}
      <div className="rounded-2xl bg-white/[0.03] px-4 ring-1 ring-white/[0.06]">{children}</div>
    </section>
  );
}

const badgeLooks = {
  neutral: "bg-white/10 text-slate-300",
  good: "bg-emerald-400/15 text-emerald-300",
  warn: "bg-amber-400/15 text-amber-300",
  bad: "bg-rose-400/15 text-rose-300",
  accent: "bg-fuchsia-500/20 text-fuchsia-300",
};

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: keyof typeof badgeLooks;
  children: ReactNode;
}) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${badgeLooks[tone]}`}>
      {children}
    </span>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="mb-4 rounded-xl bg-amber-400/10 px-3 py-2 text-xs text-amber-200 ring-1 ring-amber-300/20">
      {children}
    </div>
  );
}
