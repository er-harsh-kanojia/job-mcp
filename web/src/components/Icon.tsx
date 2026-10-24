import type { ReactNode, SVGProps } from 'react';

// Stroke icons drawn from the design (24x24, stroke 1.8). Decorative unless a label is given.
const P = {
  logo: (<><path d="M4 7h11M4 12h7M4 17h5" /><circle cx="17" cy="15" r="3.5" /><path d="m19.5 17.5 2 2" /></>),
  dashboard: (<><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>),
  search: (<><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>),
  applications: (<><path d="M11 6h10M11 12h10M11 18h10" /><path d="m3 6 1.5 1.5L7 5M3 12l1.5 1.5L7 11M3 18l1.5 1.5L7 17" /></>),
  resume: (<><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" /><path d="M14 3v5h5" /><path d="m9 14 2 2 4-4" /></>),
  platforms: (<><path d="M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0z" /><path d="M12 17v5" /></>),
  profile: (<><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>),
  sun: (<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>),
  moon: <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />,
  warn: (<><path d="M12 3 2 20h20z" /><path d="M12 10v4M12 17h.01" /></>),
  server: (<><rect x="3" y="4" width="18" height="7" rx="1.5" /><rect x="3" y="13" width="18" height="7" rx="1.5" /><path d="M7 7.5h.01M7 16.5h.01" /></>),
  retry: (<><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 4v7h-7" /></>),
  play: <path d="M7 4v16l13-8z" />,
  x: <path d="M18 6 6 18M6 6l12 12" />,
  bolt: <path d="M13 2 4 14h7l-1 8 9-12h-7z" />,
  compare: (<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M12 4v16" /></>),
  back: <path d="M19 12H5M11 6l-6 6 6 6" />,
  stop: <rect x="6" y="6" width="12" height="12" rx="1.5" />,
  external: (<><path d="M14 4h6v6M20 4l-9 9" /><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></>),
  lock: (<><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>),
  check: <path d="m5 12 5 5 9-10" />,
  chevDown: <path d="m6 9 6 6 6-6" />,
  chevUp: <path d="m6 15 6-6 6 6" />,
  file: (<><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" /><path d="M14 3v5h5" /></>),
  upload: (<><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" /><path d="M14 3v5h5" /><path d="M12 18v-6M9 15l3-3 3 3" /></>),
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  filter: <path d="M4 6h16M7 12h10M10 18h4" />,
  send: (<><path d="M5 12h13" /><path d="m12 5 7 7-7 7" /></>),
  chat: <path d="M4 5h16v11H9l-5 4z" />,
  key: (<><circle cx="8" cy="15" r="4" /><path d="m11 12 9-9M17 6l3 3M15 8l2 2" /></>),
  copy: (<><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3" /></>),
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof P;

type Props = SVGProps<SVGSVGElement> & { name: IconName; small?: boolean; label?: string };

export function Icon({ name, small, label, className, ...rest }: Props) {
  return (
    <svg
      className={`ic${small ? ' ic-sm' : ''}${className ? ` ${className}` : ''}`}
      viewBox="0 0 24 24"
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? 'img' : undefined}
      focusable="false"
      {...rest}
    >
      {P[name]}
    </svg>
  );
}
