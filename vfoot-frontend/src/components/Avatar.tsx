import { useMemo } from 'react';
import clsx from 'clsx';
import { avatarDataUri, defaultAvatarDataUri, parseAvatar } from '../utils/avatar';

// Renders a user's avatar from their opaque descriptor. With no descriptor it
// falls back to a stable illustration seeded from the username, so every account
// has a distinct picture from day one.
export default function Avatar({
  descriptor,
  username,
  size = 40,
  className,
}: {
  descriptor?: string | null;
  username?: string | null;
  size?: number;
  className?: string;
}) {
  const uri = useMemo(() => {
    const opts = parseAvatar(descriptor);
    // Render at 2x for crispness on high-density screens.
    return opts ? avatarDataUri(opts, size * 2) : defaultAvatarDataUri(username ?? 'vfoot', size * 2);
  }, [descriptor, username, size]);

  return (
    <img
      src={uri}
      width={size}
      height={size}
      alt={username ? `Avatar di ${username}` : 'Avatar'}
      className={clsx('shrink-0 rounded-full bg-surface object-cover', className)}
      style={{ width: size, height: size }}
    />
  );
}
