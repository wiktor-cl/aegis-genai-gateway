const STATUS_STYLES: Record<string, string> = {
  completed: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  running: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  failed: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
  blocked_by_guardrail: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  budget_exceeded: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  max_steps_exceeded: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
}

export function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300'
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${style}`}>
      {status.replaceAll('_', ' ')}
    </span>
  )
}
