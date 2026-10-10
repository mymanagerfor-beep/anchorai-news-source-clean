const STYLES = {
  draft: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  queued: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  validating: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  generating: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  retrieving: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  rendering: "bg-indigo-500/15 text-indigo-200 border-indigo-500/30",
  completed: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  failed: "bg-red-500/15 text-red-300 border-red-500/30",
  cancelled: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
};
const ACTIVE = ["queued", "validating", "generating", "retrieving", "rendering"];
export const STEPS = ["queued", "validating", "generating", "retrieving", "rendering", "completed"];

export const StatusChip = ({ status, testId }) => (
  <span data-testid={testId || `job-status-chip-${status}`}
    className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold capitalize ${STYLES[status] || STYLES.draft}`}>
    {ACTIVE.includes(status) && <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse" />}
    {status}
  </span>
);

export const StageBar = ({ status }) => {
  const idx = STEPS.indexOf(status);
  return (
    <div className="flex gap-1" data-testid="job-stage-bar">
      {STEPS.map((s, i) => (
        <div key={s} title={s}
          className={`h-1.5 flex-1 rounded-full ${status === "failed" || status === "cancelled" ? "bg-slate-700"
            : i < idx ? "bg-emerald-500" : i === idx ? (s === "completed" ? "bg-emerald-500" : "bg-blue-500 animate-pulse") : "bg-slate-700"}`} />
      ))}
    </div>
  );
};

export const isActive = (s) => ACTIVE.includes(s);
