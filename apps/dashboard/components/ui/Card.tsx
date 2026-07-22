import type { ReactNode } from 'react';

/**
 * Standard white card: subtle border, light shadow, p-5 padding.
 * Use `padded={false}` when the card manages its own inner layout
 * (tables, split headers).
 */
export default function Card({
  children,
  className = '',
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={`panel ${padded ? 'p-5' : ''} ${className}`.trim()}>
      {children}
    </section>
  );
}
