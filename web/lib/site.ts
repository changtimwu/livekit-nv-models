// Site branding, baked in at build time (NEXT_PUBLIC_*). Defaults = the hotel demo, so the
// existing sites are unchanged; the 愛比食堂 bendon demo sets its own (issue #20).
export const SITE = {
  title: process.env.NEXT_PUBLIC_SITE_TITLE ?? 'The LiveKit Hotel',
  description:
    process.env.NEXT_PUBLIC_SITE_DESCRIPTION ??
    'Call the front desk of The LiveKit Hotel (voice AI running on local models)',
  heading: process.env.NEXT_PUBLIC_SITE_HEADING ?? 'Call the front desk of The LiveKit Hotel',
  loginPrompt: process.env.NEXT_PUBLIC_LOGIN_PROMPT ?? 'Enter the password to call the front desk.',
  footer:
    process.env.NEXT_PUBLIC_SITE_FOOTER ??
    'Book a room, ask about the restaurant, or check a reservation. Everything runs on local models, so the first reply can take a moment.',
  disclaimer: process.env.NEXT_PUBLIC_DISCLAIMER ?? '',
  htmlLang: process.env.NEXT_PUBLIC_HTML_LANG ?? 'en',
  // Live order view fed by the agent's "bendon.order" text stream.
  orderPanel: process.env.NEXT_PUBLIC_ORDER_PANEL === '1',
  // Stores the caller can pick before the call (bendon demo, #22); empty = no picker.
  stores: parseStores(process.env.NEXT_PUBLIC_STORES),
};

export type StoreOption = { slug: string; name: string; blurb: string; delivers: boolean };

function parseStores(raw: string | undefined): StoreOption[] {
  if (!raw) return [];
  try {
    return JSON.parse(raw) as StoreOption[];
  } catch {
    return [];
  }
}
