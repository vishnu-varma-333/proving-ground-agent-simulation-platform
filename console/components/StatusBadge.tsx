type Variant = "success" | "danger" | "warning" | "neutral" | "accent";

const VARIANT_CLASSES: Record<Variant, string> = {
  success: "text-success bg-success-bg",
  danger: "text-danger bg-danger-bg",
  warning: "text-warning bg-warning-bg",
  neutral: "text-text-muted bg-neutral-bg",
  accent: "text-accent-strong bg-accent-bg",
};

export function StatusBadge({
  label,
  variant,
}: {
  label: string;
  variant: Variant;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium tracking-wide ${VARIANT_CLASSES[variant]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {label}
    </span>
  );
}

export function simulationStateVariant(state: string): Variant {
  switch (state) {
    case "completed":
      return "success";
    case "failed":
      return "danger";
    case "running":
      return "accent";
    default:
      return "neutral";
  }
}

export function runStatusVariant(status: string): Variant {
  switch (status) {
    case "completed":
      return "success";
    case "failed":
      return "danger";
    case "running":
      return "accent";
    default:
      return "neutral";
  }
}
