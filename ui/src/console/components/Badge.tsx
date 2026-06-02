import { CATEGORY_COLORS } from '@/console/types';
import type { Category } from '@/console/types';

interface BadgeProps {
  category?: Category;
  children: React.ReactNode;
  size?: 'sm' | 'md';
  variant?: 'filled' | 'outline';
  className?: string;
}

export default function Badge({ category, children, size = 'sm', variant = 'filled', className = '' }: BadgeProps) {
  const color = category ? CATEGORY_COLORS[category] : '#22d3ee';
  const sizeClasses = size === 'sm' 
    ? 'text-[11px] px-2 py-0.5' 
    : 'text-xs px-2.5 py-1';

  if (variant === 'outline') {
    return (
      <span
        className={`inline-flex items-center rounded-full font-medium border ${sizeClasses} ${className}`}
        style={{ borderColor: color, color }}
      >
        {children}
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center rounded-full font-medium ${sizeClasses} ${className}`}
      style={{ backgroundColor: `${color}20`, color }}
    >
      {children}
    </span>
  );
}
