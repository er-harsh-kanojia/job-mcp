import type { PlatformId } from '../api/types';

export const PLATFORM_NAMES: Record<string, string> = {
  naukri: 'Naukri',
  instahyre: 'Instahyre',
  indeed: 'Indeed',
  linkedin: 'LinkedIn',
  wellfound: 'Wellfound',
  hirist: 'Hirist',
};
export const LIVE_PLATFORMS = ['naukri', 'instahyre', 'hirist'] as const;
export const PLATFORM_ORDER = ['naukri', 'instahyre', 'hirist', 'linkedin', 'wellfound', 'indeed'];

export function platName(id: PlatformId): string {
  return PLATFORM_NAMES[id] ?? id.charAt(0).toUpperCase() + id.slice(1);
}

export function expLabel(min: number, max: number): string {
  if (min == null || min === -1) return 'Exp n/a';
  if (max === 99) return `${min}+ yrs`;
  if (max === -1 || max === min) return `${min} yrs`;
  return `${min}–${max} yrs`;
}

export function postedLabel(days: number): string {
  if (days < 0) return '—';
  if (days === 0) return 'Today';
  if (days < 7) return `${days}d ago`;
  if (days < 14) return '1w ago';
  if (days < 60) return `${Math.floor(days / 7)}w ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

/** Lower bound of a salary string like "22–32 LPA", for sorting. 0 when undisclosed. */
export function salaryLow(s: string): number {
  const m = /(\d+(?:\.\d+)?)/.exec(s || '');
  return m ? parseFloat(m[1]) : 0;
}

/** Match colour from the design: green at 0.70 and above, accent at 0.45 and above, muted below. */
export function matchColor(m: number): string {
  return m >= 0.7 ? 'var(--success)' : m >= 0.45 ? 'var(--accent)' : 'var(--text-3)';
}

export function pct(n: number): string {
  return `${Math.round(Math.max(0, Math.min(1, n)) * 100)}%`;
}

export function joinList(a: string[]): string {
  if (a.length <= 1) return a.join('');
  return `${a.slice(0, -1).join(', ')} and ${a[a.length - 1]}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

export function parseTime(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

const two = (n: number) => String(n).padStart(2, '0');
export function hhmm(d: Date): string {
  return `${two(d.getHours())}:${two(d.getMinutes())}`;
}

function dayDiff(d: Date, now = new Date()): number {
  const a = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const b = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  return Math.round((b - a) / 86400000);
}

export function daysAgo(iso: string): number {
  const d = parseTime(iso);
  return d ? dayDiff(d) : Infinity;
}

/** "Today 10:42", "Yest. 18:20", "1 Oct 16:05" (tracker dates). */
export function fmtStamp(iso: string): string {
  const d = parseTime(iso);
  if (!d) return '—';
  const diff = dayDiff(d);
  if (diff === 0) return `Today ${hhmm(d)}`;
  if (diff === 1) return `Yest. ${hhmm(d)}`;
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${hhmm(d)}`;
}

/** "10:42", "Yesterday", "1 Oct" (activity feed). */
export function fmtFeedTime(iso: string): string {
  const d = parseTime(iso);
  if (!d) return '';
  const diff = dayDiff(d);
  if (diff === 0) return hhmm(d);
  if (diff === 1) return 'Yesterday';
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

/** "Today, 09:40", "Yesterday, 18:20", "1 Oct, 16:05". */
export function fmtDayTime(iso: string | null | undefined): string {
  const d = parseTime(iso);
  if (!d) return '—';
  const diff = dayDiff(d);
  if (diff === 0) return `Today, ${hhmm(d)}`;
  if (diff === 1) return `Yesterday, ${hhmm(d)}`;
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${hhmm(d)}`;
}

/** "Today 10:31", "Yesterday 18:20", "1 Oct 16:05". */
export function fmtDayTimeShort(iso: string | null | undefined): string {
  return fmtDayTime(iso).replace(',', '');
}

export function fmtShortDate(iso: string | null | undefined): string {
  const d = parseTime(iso);
  return d ? `${d.getDate()} ${MONTHS[d.getMonth()]}` : '—';
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  const d = parseTime(iso);
  if (!d) return '';
  const s = Math.max(0, Math.round((now - d.getTime()) / 1000));
  if (s < 45) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

export function fmtLongDate(d = new Date()): string {
  return `${DAYS[d.getDay()]}, ${d.getDate()} ${MONTHS_LONG[d.getMonth()]}`;
}

/** Monday of the current week, like "Mon 5 Oct". */
export function weekStartLabel(now = new Date()): string {
  const d = new Date(now);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return `Mon ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function fileKind(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  return ext === 'pdf' ? 'PDF' : ext === 'doc' || ext === 'docx' ? 'Word' : ext.toUpperCase();
}

const SKILL_NAMES: Record<string, string> = {
  python: 'Python', 'machine learning': 'ML', ml: 'ML', 'deep learning': 'DL', dl: 'DL', nlp: 'NLP',
  'generative ai': 'GenAI', genai: 'GenAI', llm: 'LLM', langchain: 'LangChain', rag: 'RAG',
  tensorflow: 'TensorFlow', pytorch: 'PyTorch', 'scikit-learn': 'scikit-learn', mlops: 'MLOps',
  'computer vision': 'CV', cv: 'CV', aws: 'AWS', gcp: 'GCP', azure: 'Azure', sql: 'SQL', docker: 'Docker',
};
/** Display name for a skill key from autofill.experience ("machine learning" becomes "ML"). */
export function skillLabel(k: string): string {
  return SKILL_NAMES[k.toLowerCase()] ?? k.replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Case-insensitive skill match used for the "matches your profile" tags. */
export function skillMatches(skill: string, mine: string[]): boolean {
  const s = skill.toLowerCase();
  return mine.some((m) => {
    const k = m.toLowerCase();
    return k === s || skillLabel(m).toLowerCase() === s;
  });
}
