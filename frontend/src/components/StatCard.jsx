export default function StatCard({ label, value, hint, icon: Icon }) {
  return (
    <div className="card transition hover:-translate-y-0.5 hover:shadow-lg">
      <div className="flex items-start justify-between">
        <div className="text-sm font-medium text-slate-500 dark:text-slate-400">{label}</div>
        {Icon && (
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-900/40 dark:text-brand-300">
            <Icon className="h-[18px] w-[18px]" />
          </div>
        )}
      </div>
      <div className="mt-3 text-3xl font-semibold tracking-tight text-slate-900 dark:text-white">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</div>}
    </div>
  )
}
