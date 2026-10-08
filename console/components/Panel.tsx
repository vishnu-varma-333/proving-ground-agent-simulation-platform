export function Panel({
  title,
  description,
  children,
  className = "",
}: {
  title?: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-lg border border-border bg-bg-raised ${className}`}
    >
      {title && (
        <header className="border-b border-border-muted px-5 py-3.5">
          <h2 className="text-sm font-medium text-text">{title}</h2>
          {description && (
            <p className="mt-0.5 text-xs text-text-faint">{description}</p>
          )}
        </header>
      )}
      <div>{children}</div>
    </section>
  );
}
