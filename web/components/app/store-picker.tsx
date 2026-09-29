'use client';

import { cn } from '@/lib/shadcn/utils';
import type { StoreOption } from '@/lib/site';

/** Pick which store the voice agent answers for, before the call starts (#22). */
export function StorePicker({
  stores,
  value,
  onChange,
}: {
  stores: StoreOption[];
  value: string;
  onChange: (slug: string) => void;
}) {
  return (
    <div role="radiogroup" aria-label="選擇店家" className="mt-6 grid w-full max-w-md gap-2 px-4">
      {stores.map((s) => {
        const selected = s.slug === value;
        return (
          <button
            key={s.slug}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(s.slug)}
            className={cn(
              'flex items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left transition-colors',
              selected ? 'border-primary bg-primary/10' : 'hover:bg-muted'
            )}
          >
            <span>
              <span className="text-foreground block font-medium">{s.name}</span>
              <span className="text-muted-foreground block text-xs">{s.blurb}</span>
            </span>
            <span className="text-muted-foreground shrink-0 text-xs">
              {s.delivers ? '自取・外送' : '僅自取'}
            </span>
          </button>
        );
      })}
    </div>
  );
}
