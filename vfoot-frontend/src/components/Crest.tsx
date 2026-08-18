import { useEffect, useId, useMemo, useState } from 'react';
import clsx from 'clsx';
import { crestImageUrl } from '../api';
import {
  CREST_OUTLINES,
  crestBands,
  crestColor,
  crestImageHash,
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
 *
 *  An uploaded image is drawn INSIDE the same clip as the composed layers, so it
 *  takes the shield/circle/pennant silhouette and the same outline. That is what
 *  keeps a row of standings coherent when half the league composed a crest and
 *  half uploaded a photo — without the clip a mixed league reads as a collage.
 *
 *  If the image does not load — revoked by an admin, absent from a dev copy, a
 *  request that failed on a train — we fall back to the composed layers, which
 *  are still in the descriptor. Never a grey box, and never a cleanup pass on
 *  the descriptors of everyone who was using it.
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

  const hash = crestImageHash(opts.img);
  const [failed, setFailed] = useState(false);
  // A different image deserves a fresh chance: without this, one crest that
  // 404s would poison the component for every descriptor it renders next (the
  // same <Crest> instance is reused as a table re-sorts).
  useEffect(() => setFailed(false), [hash]);
  const showImage = hash !== '' && !failed;

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
      {showImage ? (
        <g clipPath={`url(#${clipId})`}>
          {/* Un fondo sotto l'immagine: una figura con la trasparenza non deve
              lasciar vedere quello che c'è dietro nella pagina. */}
          <rect x={0} y={0} width={64} height={64} fill={crestColor(opts.primary, '1e3a8a')} />
          <image
            href={crestImageUrl(hash)}
            x={0}
            y={0}
            width={64}
            height={64}
            preserveAspectRatio="xMidYMid slice"
            onError={() => setFailed(true)}
          />
        </g>
      ) : (
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
      )}
      {/* L'orlo viene dal tema (v. --vf-crest-edge): è ciò che distingue lo
          scudo dal tondo, e un colore fisso lo faceva sparire su fondo scuro,
          dove la sagoma restava leggibile solo se l'immagine dentro era chiara. */}
      <path d={outline} fill="none" stroke="var(--vf-crest-edge)" strokeWidth={2.5} />
      {showImage ? null : symbol ? (
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
