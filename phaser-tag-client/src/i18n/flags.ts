/**
 * Hand-written flag SVGs (one per region). Emoji flags are not used:
 * Windows does not render them. These drawings are original, not copied
 * from a flag-icon set.
 */
import type { Locale } from "./detect.ts";

const NS = 'xmlns="http://www.w3.org/2000/svg"';

function star(cx: number, cy: number, r: number, points: number): string {
  const pts: string[] = [];
  for (let i = 0; i < points * 2; i++) {
    const ang = (Math.PI / points) * i - Math.PI / 2;
    const rad = i % 2 === 0 ? r : r * 0.4;
    pts.push(`${(cx + rad * Math.cos(ang)).toFixed(2)},${(cy + rad * Math.sin(ang)).toFixed(2)}`);
  }
  return pts.join(" ");
}

/** Union Jack in a 60×30 box. Simplified, still reads at button size. */
function unionJack(): string {
  return `
    <rect width="60" height="30" fill="#012169"/>
    <path d="M0 0 L60 30 M60 0 L0 30" stroke="#ffffff" stroke-width="8"/>
    <path d="M0 0 L60 30 M60 0 L0 30" stroke="#C8102E" stroke-width="3"/>
    <path d="M30 0 V30 M0 15 H60" stroke="#ffffff" stroke-width="14"/>
    <path d="M30 0 V30 M0 15 H60" stroke="#C8102E" stroke-width="8"/>`;
}

function us(): string {
  const stripes: string[] = [];
  for (let i = 0; i < 13; i++) {
    if (i % 2 === 0) stripes.push(`<rect y="${(i * 40) / 13}" width="60" height="${40 / 13 + 0.2}" fill="#bf0a30"/>`);
    else stripes.push(`<rect y="${(i * 40) / 13}" width="60" height="${40 / 13 + 0.2}" fill="#ffffff"/>`);
  }
  const stars: string[] = [];
  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 5; col++) {
      const x = 2.6 + col * 4.2;
      const y = 2.4 + row * 4.2;
      stars.push(`<polygon points="${star(x, y, 1.15, 5)}" fill="#ffffff"/>`);
    }
  }
  return `
    ${stripes.join("")}
    <rect width="24" height="18.5" fill="#002868"/>
    ${stars.join("")}`;
}

function gb(): string {
  return `<svg ${NS} viewBox="0 0 60 30" preserveAspectRatio="xMidYMid slice">${unionJack()}</svg>`;
}

function au(): string {
  return `
    <rect width="60" height="40" fill="#012169"/>
    <svg x="0" y="0" width="30" height="20" viewBox="0 0 60 30">${unionJack()}</svg>
    <polygon points="${star(15, 31, 4.2, 7)}" fill="#ffffff"/>
    <polygon points="${star(42, 12, 2.1, 7)}" fill="#ffffff"/>
    <polygon points="${star(50, 18, 2.1, 7)}" fill="#ffffff"/>
    <polygon points="${star(46, 28, 2.1, 7)}" fill="#ffffff"/>
    <polygon points="${star(38, 26, 1.3, 5)}" fill="#ffffff"/>
    <polygon points="${star(34, 18, 2.3, 7)}" fill="#ffffff"/>`;
}

function mx(): string {
  return `
    <rect width="20" height="40" fill="#006847"/>
    <rect x="20" width="20" height="40" fill="#ffffff"/>
    <rect x="40" width="20" height="40" fill="#ce1126"/>
    <circle cx="30" cy="20" r="5.2" fill="#8c5a2b"/>
    <path d="M30 14.5 v7 M27.2 18.2 h5.6" stroke="#1f6b32" stroke-width="1.4" stroke-linecap="round"/>
    <path d="M26.4 22.4 q3.6 2.4 7.2 0" fill="none" stroke="#1f6b32" stroke-width="1.1"/>`;
}

function co(): string {
  return `
    <rect width="60" height="20" fill="#fcd116"/>
    <rect y="20" width="60" height="10" fill="#003893"/>
    <rect y="30" width="60" height="10" fill="#ce1126"/>`;
}

function dom(): string {
  return `
    <rect width="30" height="20" fill="#002d62"/>
    <rect x="30" width="30" height="20" fill="#ce1126"/>
    <rect y="20" width="30" height="20" fill="#ce1126"/>
    <rect x="30" y="20" width="30" height="20" fill="#002d62"/>
    <rect x="26" width="8" height="40" fill="#ffffff"/>
    <rect y="16" width="60" height="8" fill="#ffffff"/>
    <circle cx="30" cy="20" r="3.2" fill="#ce1126"/>`;
}

function es(): string {
  return `
    <rect width="60" height="40" fill="#c60b1e"/>
    <rect y="10" width="60" height="20" fill="#ffc400"/>
    <path d="M27 15 h6 v8 a3 3 0 0 1-6 0 z" fill="#c60b1e"/>
    <rect x="28.6" y="17" width="2.8" height="4.2" fill="#ffc400"/>`;
}

function ar(): string {
  const rays: string[] = [];
  for (let i = 0; i < 16; i++) {
    const ang = (Math.PI / 8) * i;
    const x1 = 30 + Math.cos(ang) * 4.2;
    const y1 = 20 + Math.sin(ang) * 4.2;
    const x2 = 30 + Math.cos(ang) * 7.2;
    const y2 = 20 + Math.sin(ang) * 7.2;
    rays.push(`<line x1="${x1.toFixed(2)}" y1="${y1.toFixed(2)}" x2="${x2.toFixed(2)}" y2="${y2.toFixed(2)}" stroke="#f6b40e" stroke-width="1.3" stroke-linecap="round"/>`);
  }
  return `
    <rect width="60" height="13.4" fill="#74acdf"/>
    <rect y="13.3" width="60" height="13.4" fill="#ffffff"/>
    <rect y="26.6" width="60" height="13.4" fill="#74acdf"/>
    ${rays.join("")}
    <circle cx="30" cy="20" r="3.6" fill="#f6b40e"/>`;
}

function cn(): string {
  const small = [
    star(22, 8, 1.7, 5),
    star(26, 12, 1.7, 5),
    star(26, 18, 1.7, 5),
    star(22, 22, 1.7, 5),
  ];
  return `
    <rect width="60" height="40" fill="#de2910"/>
    <polygon points="${star(12, 12, 5, 5)}" fill="#ffde00"/>
    ${small.map(points => `<polygon points="${points}" fill="#ffde00"/>`).join("")}`;
}

function jp(): string {
  return `
    <rect width="60" height="40" fill="#ffffff"/>
    <circle cx="30" cy="20" r="9" fill="#bc002d"/>`;
}

/** Saffron, white, green, and a 24-spoke chakra. */
function india(): string {
  const spokes: string[] = [];
  for (let i = 0; i < 24; i++) {
    const ang = (Math.PI / 12) * i;
    const x2 = (30 + Math.cos(ang) * 5.3).toFixed(2);
    const y2 = (20 + Math.sin(ang) * 5.3).toFixed(2);
    spokes.push(`<line x1="30" y1="20" x2="${x2}" y2="${y2}" stroke="#000080" stroke-width="0.45"/>`);
  }
  return `
    <rect width="60" height="13.34" fill="#ff9933"/>
    <rect y="13.33" width="60" height="13.34" fill="#ffffff"/>
    <rect y="26.66" width="60" height="13.34" fill="#138808"/>
    <circle cx="30" cy="20" r="5.6" fill="none" stroke="#000080" stroke-width="0.7"/>
    ${spokes.join("")}
    <circle cx="30" cy="20" r="0.85" fill="#000080"/>`;
}

/** Green field, white hoist stripe, crescent and star. */
function pakistan(): string {
  return `
    <rect width="60" height="40" fill="#01411c"/>
    <rect width="15" height="40" fill="#ffffff"/>
    <circle cx="33.2" cy="20" r="7" fill="#ffffff"/>
    <circle cx="35.4" cy="18.6" r="5.9" fill="#01411c"/>
    <polygon points="${star(41.2, 20, 2.5, 5)}" fill="#ffffff"/>`;
}

const BODIES: Record<Locale, () => string> = {
  "en-US": us,
  "en-GB": () => unionJack(),
  "en-AU": au,
  "es-MX": mx,
  "es-CO": co,
  "es-DO": dom,
  "es-ES": es,
  "es-AR": ar,
  "zh-CN": cn,
  "ja-JP": jp,
  "hi-IN": india,
  "ur-PK": pakistan,
};

/** Inline SVG for `locale`'s region. GB is 2:1; the rest are 3:2. */
export function flagSvg(locale: Locale): string {
  if (locale === "en-GB") return gb();
  return `<svg ${NS} viewBox="0 0 60 40" preserveAspectRatio="xMidYMid slice">${BODIES[locale]()}</svg>`;
}
