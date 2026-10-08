export function Mono({
  children,
  title,
}: {
  children: string;
  title?: string;
}) {
  return (
    <span
      title={title ?? children}
      className="font-mono text-[13px] tracking-tight text-text-muted"
    >
      {children}
    </span>
  );
}
