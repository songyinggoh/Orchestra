import { Link } from 'react-router';

export function NotFoundPage() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4">
      <p className="text-4xl font-bold text-zinc-700">404</p>
      <p className="text-sm text-zinc-500">Page not found</p>
      <Link
        to="/runs"
        className="text-sm text-violet-400 underline-offset-4 hover:underline"
      >
        Back to runs
      </Link>
    </div>
  );
}
