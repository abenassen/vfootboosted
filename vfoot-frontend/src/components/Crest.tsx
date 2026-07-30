import { useId, useMemo } from 'react';
import clsx from 'clsx';
import {
  CREST_OUTLINES,
  crestBands,
  crestColor,
  crestInitials,
  crestSymbol,
  defaultCrest,
  parseCrest,
} from '../utils/crest';

/** A team's crest. With no descriptor it falls back to one seeded from the team
 *  name, so a league looks like ten different clubs before anyone opens the
 *  editor.
 *
 *  Rendered as JSX, not as an SVG string dropped in with dangerouslySetInnerHTML:
 *  both the team name and the descriptor are written by other members of the
 *  league, and building markup out of them would be stored XSS. Here React
 *  escapes the text, and colours are validated against the catalogue.
 */
export default function Crest({
  descriptor,
  teamName,
  size = 32,
  className,
}: {
  descriptor?: string | null;
  teamName?: string | null;
  size?: number;
  className?: string;
}) {
  // clipPath ids are document-global: a standings table draws ten crests, and
  // without a unique id every one of them would be clipped by the first.
  const clipId = `crest-${useId()}`;
  const opts = useMemo(
    () => parseCrest(descriptor) ?? defaultCrest(teamName),
    [descriptor, teamName],
  );

  const outline = CREST_OUTLINES[opts.shape] ?? CREST_OUTLINES.shield;
  const bands = crestBands(opts.pattern);
  const symbol = crestSymbol(opts.symbol);
  const initials = crestInitials(teamName);

  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      role="img"
      aria-label={teamName ? `Stemma di ${teamName}` : 'Stemma'}
      className={clsx('shrink-0', className)}
    >
      <defs>
        <clipPath id={clipId}>
          <path d={outline} />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clipId})`}>
        <rect x={0} y={0} width={64} height={64} fill={crestColor(opts.primary, '1e3a8a')} />
        {bands.map((b, i) =>
          b.kind === 'rect' ? (
            <rect
              key={i}
              x={b.x}
              y={b.y}
              width={b.width}
              height={b.height}
              fill={crestColor(opts.secondary, 'ffffff')}
            />
          ) : (
            <path key={i} d={b.d} fill={crestColor(opts.secondary, 'ffffff')} />
          ),
        )}
      </g>
      <path d={outline} fill="none" stroke="rgba(15,23,42,0.45)" strokeWidth={2.5} />
      {symbol ? (
        <text x={32} y={36} textAnchor="middle" dominantBaseline="central" fontSize={26}>
          {symbol}
        </text>
      ) : (
        <text
          x={32}
          y={35}
          textAnchor="middle"
          dominantBaseline="central"
          fill={crestColor(opts.ink, 'ffffff')}
          fontFamily="system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
          fontSize={initials.length > 2 ? 19 : 25}
          fontWeight={800}
        >
          {initials}
        </text>
      )}
    </svg>
  );
}
