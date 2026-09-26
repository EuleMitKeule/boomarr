export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 256 256" className={className} aria-hidden>
      <defs>
        <linearGradient id="boomarr-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ff8a3d" />
          <stop offset="1" stopColor="#e5484d" />
        </linearGradient>
      </defs>
      <rect width="256" height="256" rx="56" fill="url(#boomarr-bg)" />
      <path d="M52 104h30l38-32v112l-38-32H52z" fill="#fff" />
      <g fill="none" stroke="#fff" strokeWidth="14" strokeLinecap="round">
        <path d="M146 100a40 40 0 0 1 0 56" />
        <path d="M168 78a72 72 0 0 1 0 100" />
        <path d="M190 56a104 104 0 0 1 0 144" opacity=".55" />
      </g>
    </svg>
  );
}
