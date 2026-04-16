import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Merge Tailwind class names, collapsing conflicts.
 *
 * Standard shadcn/ui helper. Used by every generated primitive under
 * `src/components/ui/`.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
