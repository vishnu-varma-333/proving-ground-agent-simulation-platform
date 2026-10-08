import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center gap-3 py-24 text-center">
      <p className="font-mono text-xs text-text-faint">404</p>
      <h1 className="text-lg font-semibold text-text">Not found</h1>
      <p className="max-w-sm text-sm text-text-faint">
        That run or simulation doesn&apos;t exist, or hasn&apos;t been recorded
        yet.
      </p>
      <Link
        href="/"
        className="mt-2 text-sm text-accent-strong hover:underline"
      >
        Back to runs
      </Link>
    </div>
  );
}
