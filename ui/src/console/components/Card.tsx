import type { ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  className?: string;
  noPadding?: boolean;
}

export default function Card({ children, className = '', noPadding = false }: CardProps) {
  return (
    <div
      className={`
        bg-[#111827]/90 rounded-xl border border-white/5
        shadow-[0_1px_3px_rgba(0,0,0,0.3)]
        ${noPadding ? '' : 'p-6'}
        ${className}
      `}
    >
      {children}
    </div>
  );
}
