import { useEffect, useRef, type ReactNode } from 'react';
import type { AppStatus, PlatformId, SessionState } from '../api/types';
import { matchColor, pct, platName } from '../lib/format';
import { Icon, type IconName } from './Icon';

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}

export function PlatformBadge({ id, name, large, soon, className }: { id: PlatformId; name?: string; large?: boolean; soon?: boolean; className?: string }) {
  return (
    <span className={cx('pbadge', `p-${id}`, large && 'pbadge-lg', soon && 'pbadge-soon', className)}>
      <span className="pdot" aria-hidden="true" />
      {name ?? platName(id)}
    </span>
  );
}

export function MatchScore({ value, large, className }: { value: number; large?: boolean; className?: string }) {
  return (
    <span className={cx('c-match', className)}>
      <span className={cx('mbar', large && 'mbar-lg')} aria-hidden="true">
        <span style={{ width: pct(value), background: matchColor(value) }} />
      </span>
      <span className="mono" style={{ fontWeight: 500 }}>
        {value.toFixed(2)}
      </span>
    </span>
  );
}

const STATUS: Record<AppStatus, [string, string]> = {
  applied: ['st-applied', 'Applied'],
  failed: ['st-failed', 'Failed'],
  skipped: ['st-skipped', 'Skipped'],
  dry_run: ['st-dry', 'Dry run'],
};
export function StatusPill({ status }: { status: AppStatus }) {
  const [c, l] = STATUS[status];
  return <span className={`pill ${c}`}>{l}</span>;
}

export function Pill({ tone, spin, children }: { tone: string; spin?: boolean; children: ReactNode }) {
  return (
    <span className={`pill ${tone}`}>
      {spin && <span className="spin" aria-hidden="true" />}
      {children}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <span className="kbd">{children}</span>;
}

export function Spinner({ large, className, style }: { large?: boolean; className?: string; style?: React.CSSProperties }) {
  return <span className={cx('spin', large && 'spin-lg', className)} style={style} aria-hidden="true" />;
}

export function Alert({
  tone,
  icon = 'warn',
  title,
  children,
  actions,
  role = 'status',
}: {
  tone: 'warn' | 'danger' | 'info' | 'live';
  icon?: IconName;
  title: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  role?: 'status' | 'alert';
}) {
  return (
    <div className={`alert alert-${tone}`} role={role}>
      <Icon name={icon} />
      <div className="alert-body">
        <div className="alert-title">{title}</div>
        {children && <div>{children}</div>}
      </div>
      {actions && <div className="alert-actions">{actions}</div>}
    </div>
  );
}

export function EmptyState({ icon, title, children, action, className }: { icon?: IconName; title: ReactNode; children?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cx('empty', className)}>
      {icon && (
        <span className="empty-ic">
          <Icon name={icon} />
        </span>
      )}
      <div className="h2">{title}</div>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

const SESSION_DOT: Record<SessionState, string> = {
  logged_in: 'sdot-ok',
  expired: 'sdot-expired',
  not_set_up: 'sdot-none',
  unknown: 'sdot-unknown',
};
export const SESSION_LABEL: Record<SessionState, string> = {
  logged_in: 'Logged in',
  expired: 'Session expired',
  not_set_up: 'Not set up',
  unknown: 'Unknown',
};
export function SessionDot({ state, label }: { state: SessionState; label?: string }) {
  return <span className={`sdot ${SESSION_DOT[state]}`} role={label ? 'img' : undefined} aria-label={label} />;
}

export function Bar({ value, color, className, style }: { value: number; color: string; className?: string; style?: React.CSSProperties }) {
  return (
    <span className={cx('hbar', className)} style={style} aria-hidden="true">
      <span style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: color }} />
    </span>
  );
}

/**
 * Modal surface: scrim + panel, closes on Escape and scrim click, moves focus into the panel
 * and restores it on close. `variant` picks the design's drawer/center/top placements.
 */
export function Overlay({
  variant,
  onClose,
  scrimLabel,
  children,
}: {
  variant: 'right' | 'center' | 'top' | 'left';
  onClose: () => void;
  scrimLabel: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    // Leave focus alone if something inside (an autoFocus input) already took it; otherwise focus the dialog itself.
    if (!el?.contains(document.activeElement)) {
      const panel = el?.querySelector<HTMLElement>('[role="dialog"]');
      if (panel) {
        if (!panel.hasAttribute('tabindex')) panel.setAttribute('tabindex', '-1');
        panel.focus();
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        closeRef.current();
      }
      if (e.key === 'Tab' && el) {
        const items = Array.from(el.querySelectorAll<HTMLElement>('button:not([disabled]):not([data-scrim]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'));
        if (!items.length) return;
        const a = items[0];
        const z = items[items.length - 1];
        if (e.shiftKey && document.activeElement === a) {
          e.preventDefault();
          z.focus();
        } else if (!e.shiftKey && document.activeElement === z) {
          e.preventDefault();
          a.focus();
        }
      }
    };
    el?.addEventListener('keydown', onKey);
    return () => {
      el?.removeEventListener('keydown', onKey);
      prev?.focus?.();
    };
  }, []);
  const cls = variant === 'center' ? 'overlay overlay-center' : variant === 'top' ? 'overlay overlay-top' : variant === 'left' ? 'overlay overlay-left' : 'overlay';
  return (
    <div className={cls} ref={ref}>
      <button className="scrim" data-scrim onClick={onClose} aria-label={scrimLabel} tabIndex={-1} />
      {children}
    </div>
  );
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  const W = [
    ['60%', '30%'],
    ['45%', '25%'],
    ['70%', '35%'],
    ['52%', '28%'],
  ];
  return (
    <>
      {Array.from({ length: rows }, (_, i) => (
        <div className="trow jgrid" aria-hidden="true" key={i}>
          <span className="skel" style={{ width: 14, height: 14 }} />
          <span className="skel" style={{ width: 28 }} />
          <span style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span className="skel" style={{ width: W[i % 4][0] }} />
            <span className="skel" style={{ width: W[i % 4][1], height: 8 }} />
          </span>
          <span className="skel" style={{ width: 64 }} />
          <span className="skel" style={{ width: 70 }} />
          <span className="skel" style={{ width: 72 }} />
          <span className="skel" style={{ width: 48 }} />
          <span className="skel" style={{ width: 40 }} />
          <span className="skel" style={{ width: 60 }} />
          <span className="skel" style={{ width: 90, justifySelf: 'end' }} />
        </div>
      ))}
    </>
  );
}

export function LoadingCard({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="card" style={{ padding: 20, display: 'flex', gap: 10, alignItems: 'center', color: 'var(--text-3)' }} role="status">
      <Spinner style={{ color: 'var(--info)' }} />
      {label}
    </div>
  );
}
