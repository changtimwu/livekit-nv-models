'use client';

import { useMemo } from 'react';
import { useTextStream } from '@livekit/components-react';

const ORDER_TOPIC = 'bendon.order';

type OrderLine = {
  name: string;
  quantity: number;
  unit_price: number;
  amount: number;
  note: string;
};
type OrderSnapshot = {
  status: 'open' | 'confirmed' | 'cancelled';
  order_no: string;
  lines: OrderLine[];
  subtotal: number;
  total: number;
  mode: 'pickup' | 'delivery' | null;
  address: string;
  time: string;
  name: string;
  phone_masked: string;
  delivery_minimum: number;
};

const STATUS: Record<OrderSnapshot['status'], string> = {
  open: '點餐中',
  confirmed: '已成立',
  cancelled: '已取消',
};

/** Live view of the caller's order; the agent publishes a full snapshot after every change. */
export function OrderPanel() {
  const { textStreams } = useTextStream(ORDER_TOPIC);
  const order = useMemo<OrderSnapshot | null>(() => {
    const latest = textStreams.at(-1)?.text;
    if (!latest) return null;
    try {
      return JSON.parse(latest) as OrderSnapshot;
    } catch {
      return null;
    }
  }, [textStreams]);

  if (!order) return null;
  const short = order.mode === 'delivery' && order.subtotal < order.delivery_minimum;

  return (
    <aside className="bg-background/90 text-foreground fixed top-4 right-4 left-4 z-40 max-h-[45vh] overflow-auto rounded-xl border p-4 text-sm shadow-lg backdrop-blur md:left-auto md:w-80">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-semibold">你的訂單</h2>
        <span className="text-muted-foreground text-xs">
          {STATUS[order.status]}
          {order.order_no && ` · 單號 ${order.order_no}`}
        </span>
      </div>
      {order.lines.length === 0 ? (
        <p className="text-muted-foreground">還沒有餐點</p>
      ) : (
        <ul className="space-y-1">
          {order.lines.map((ln) => (
            <li key={ln.name + ln.note} className="flex justify-between gap-2">
              <span>
                {ln.name} × {ln.quantity}
                {ln.note && <span className="text-muted-foreground block text-xs">{ln.note}</span>}
              </span>
              <span className="tabular-nums">${ln.amount}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2 flex justify-between border-t pt-2 font-semibold">
        <span>合計</span>
        <span className="tabular-nums">${order.total}</span>
      </div>
      {order.mode && (
        <p className="text-muted-foreground mt-2 text-xs">
          {order.mode === 'pickup'
            ? `自取 · ${order.time}`
            : `外送 · ${order.address} · ${order.time}`}
        </p>
      )}
      {short && <p className="mt-1 text-xs text-amber-600">外送需滿 ${order.delivery_minimum}</p>}
      {order.name && (
        <p className="text-muted-foreground text-xs">
          {order.name} · {order.phone_masked}
        </p>
      )}
    </aside>
  );
}
