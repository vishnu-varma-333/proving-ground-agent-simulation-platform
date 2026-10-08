import Link from "next/link";

const NAV_LINKS = [
  { href: "/", label: "Runs" },
  { href: "/compare", label: "Compare" },
];

export function TopNav() {
  return (
    <header className="sticky top-0 z-10 border-b border-border bg-bg/80 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="h-2 w-2 rounded-full bg-accent" />
          <span className="text-sm font-semibold tracking-tight text-text">
            Proving Ground
          </span>
          <span className="rounded-md border border-border-muted px-1.5 py-0.5 text-[11px] font-medium text-text-faint">
            console
          </span>
        </Link>
        <nav className="flex items-center gap-5">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="text-sm text-text-muted transition-colors hover:text-text"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
