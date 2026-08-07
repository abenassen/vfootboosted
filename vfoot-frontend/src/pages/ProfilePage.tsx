import { FormEvent, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, Card, SectionTitle } from '../components/ui';
import Avatar from '../components/Avatar';
import AvatarBuilder from '../components/AvatarBuilder';
import NotificationsCard from '../components/NotificationsCard';
import { useAuth } from '../auth/AuthContext';
import { changePassword, updateProfile } from '../api';
import { ApiError } from '../api/backend';
import { AvatarOptions, DEFAULT_AVATAR, parseAvatar, serializeAvatar } from '../utils/avatar';

type Banner = { tone: 'success' | 'error'; text: string } | null;

function BannerLine({ banner }: { banner: Banner }) {
  if (!banner) return null;
  return (
    <div
      className={
        banner.tone === 'success'
          ? 'rounded-xl bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-800'
          : 'rounded-xl bg-red-50 px-3 py-2 text-sm font-medium text-red-700'
      }
    >
      {banner.text}
    </div>
  );
}

function errMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Operazione non riuscita.';
}

export default function ProfilePage() {
  const { user, updateUser } = useAuth();

  // Avatar
  const [avatar, setAvatar] = useState<AvatarOptions>(() => parseAvatar(user?.avatar) ?? DEFAULT_AVATAR);
  const [editingAvatar, setEditingAvatar] = useState(false);
  const [avatarPending, setAvatarPending] = useState(false);
  const [avatarBanner, setAvatarBanner] = useState<Banner>(null);
  const avatarChanged = useMemo(() => serializeAvatar(avatar) !== (user?.avatar ?? ''), [avatar, user?.avatar]);

  // Username
  const [username, setUsername] = useState(user?.username ?? '');
  const [usernamePending, setUsernamePending] = useState(false);
  const [usernameBanner, setUsernameBanner] = useState<Banner>(null);
  const usernameChanged = username.trim() !== (user?.username ?? '') && username.trim().length > 0;

  // Password
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [pwPending, setPwPending] = useState(false);
  const [pwBanner, setPwBanner] = useState<Banner>(null);

  async function onSaveAvatar() {
    setAvatarPending(true);
    setAvatarBanner(null);
    try {
      const updated = await updateProfile({ avatar: serializeAvatar(avatar) });
      updateUser(updated);
      setAvatarBanner({ tone: 'success', text: 'Avatar aggiornato.' });
    } catch (err) {
      setAvatarBanner({ tone: 'error', text: errMessage(err) });
    } finally {
      setAvatarPending(false);
    }
  }

  async function onSaveUsername(e: FormEvent) {
    e.preventDefault();
    setUsernamePending(true);
    setUsernameBanner(null);
    try {
      const updated = await updateProfile({ username: username.trim() });
      updateUser(updated);
      setUsername(updated.username);
      setUsernameBanner({ tone: 'success', text: 'Username aggiornato.' });
    } catch (err) {
      setUsernameBanner({ tone: 'error', text: errMessage(err) });
    } finally {
      setUsernamePending(false);
    }
  }

  async function onChangePassword(e: FormEvent) {
    e.preventDefault();
    setPwBanner(null);
    if (newPw.length < 8) {
      setPwBanner({ tone: 'error', text: 'La nuova password deve avere almeno 8 caratteri.' });
      return;
    }
    if (newPw !== confirmPw) {
      setPwBanner({ tone: 'error', text: 'La nuova password e la conferma non coincidono.' });
      return;
    }
    setPwPending(true);
    try {
      const updated = await changePassword({ current_password: currentPw, new_password: newPw });
      updateUser(updated);
      setCurrentPw('');
      setNewPw('');
      setConfirmPw('');
      setPwBanner({ tone: 'success', text: 'Password aggiornata.' });
    } catch (err) {
      setPwBanner({ tone: 'error', text: errMessage(err) });
    } finally {
      setPwPending(false);
    }
  }

  const inputClass =
    'w-full rounded-xl border border-slate-300 px-3 py-2 outline-none ring-sky-200 focus:ring';

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      {/* Identity header. Da qui in poi questa pagina è SOLO impostazioni: chi
          sei — faccia, albo d'oro, leghe — sta sulla scheda pubblica, che è la
          stessa che vedono gli altri. Tenere l'albo d'oro anche qui voleva dire
          due pagine che raccontano la stessa cosa e possono smettere di
          concordare. */}
      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-4">
            <Avatar descriptor={user?.avatar} username={user?.username} size={64} />
            <div className="min-w-0">
              <div className="text-lg font-black leading-tight">{user?.username ?? 'Utente'}</div>
              <div className="truncate text-sm text-slate-500">{user?.email || 'Email non impostata'}</div>
            </div>
          </div>
          {user ? (
            <Link to={`/fantallenatori/${user.id}`}>
              <Button size="sm" variant="secondary">🏆 La tua scheda</Button>
            </Link>
          ) : null}
        </div>
      </Card>

      {/* Notifications + install. High on the page on purpose: on iOS the
          install is a prerequisite for notifications and nothing else announces it. */}
      <NotificationsCard />

      {/* Avatar builder, CHIUSO finché non lo si chiede — come "Nome e stemma"
          nella pagina rose. È una tavolozza alta mezzo schermo (pelle, capelli,
          occhi, vestiti…), e tenerla sempre aperta spingeva sotto la piega tutto
          il resto della pagina per una cosa che si tocca una volta e poi mai più. */}
      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Avatar descriptor={user?.avatar} username={user?.username} size={44} />
            <div>
              <SectionTitle>Avatar</SectionTitle>
              <div className="text-sm text-slate-500">
                Ti identifica in ogni lega: ce n'è uno solo per account.
              </div>
            </div>
          </div>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              // Chiudere ANNULLA la bozza: lasciarla in giro significava
              // riaprire il pannello su modifiche mai salvate, con il bottone
              // "Salva" acceso per un cambiamento che non si ricorda di aver fatto.
              if (editingAvatar) setAvatar(parseAvatar(user?.avatar) ?? DEFAULT_AVATAR);
              setAvatarBanner(null);
              setEditingAvatar((open) => !open);
            }}
          >
            {editingAvatar ? 'Chiudi' : '✏️ Cambia avatar'}
          </Button>
        </div>

        {editingAvatar ? (
          <div className="mt-4 border-t pt-4">
            <AvatarBuilder value={avatar} onChange={setAvatar} />
            <div className="mt-4 flex items-center gap-3">
              <Button onClick={() => void onSaveAvatar()} disabled={!avatarChanged || avatarPending}>
                {avatarPending ? 'Salvataggio…' : 'Salva avatar'}
              </Button>
              {avatarChanged ? (
                <button
                  type="button"
                  onClick={() => setAvatar(parseAvatar(user?.avatar) ?? DEFAULT_AVATAR)}
                  className="text-sm font-semibold text-slate-500 hover:text-slate-800"
                >
                  Annulla
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
        <div className="mt-3">
          <BannerLine banner={avatarBanner} />
        </div>
      </Card>

      {/* Username */}
      <Card className="p-4">
        <SectionTitle>Username</SectionTitle>
        <form className="mt-3 space-y-3" onSubmit={onSaveUsername}>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className={inputClass}
            placeholder="Il tuo username"
          />
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={!usernameChanged || usernamePending}>
              {usernamePending ? 'Salvataggio…' : 'Salva username'}
            </Button>
          </div>
          <BannerLine banner={usernameBanner} />
        </form>
      </Card>

      {/* Email (read-only for now) */}
      <Card className="p-4">
        <SectionTitle>Email</SectionTitle>
        <div className="mt-3 text-sm text-slate-700">{user?.email || 'Email non impostata'}</div>
        <div className="mt-1 text-xs text-slate-500">
          Il cambio email arriverà più avanti: richiede una nuova conferma via link.
        </div>
      </Card>

      {/* Password */}
      <Card className="p-4">
        <SectionTitle>Cambia password</SectionTitle>
        <form className="mt-3 space-y-3" onSubmit={onChangePassword}>
          <label className="block text-sm">
            <div className="mb-1 font-semibold text-slate-700">Password attuale</div>
            <input type="password" value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} className={inputClass} autoComplete="current-password" />
          </label>
          <label className="block text-sm">
            <div className="mb-1 font-semibold text-slate-700">Nuova password</div>
            <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} className={inputClass} autoComplete="new-password" />
          </label>
          <label className="block text-sm">
            <div className="mb-1 font-semibold text-slate-700">Conferma nuova password</div>
            <input type="password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} className={inputClass} autoComplete="new-password" />
          </label>
          <Button type="submit" disabled={pwPending || !currentPw || !newPw || !confirmPw}>
            {pwPending ? 'Aggiornamento…' : 'Aggiorna password'}
          </Button>
          <BannerLine banner={pwBanner} />
        </form>
      </Card>
    </div>
  );
}
