export interface AuthUser {
  id: number;
  username: string;
  email: string;
  /** Opaque, client-owned avatar descriptor (a JSON string of avataaars
   *  options). Empty string => no avatar chosen; the UI falls back to a
   *  deterministic default seeded from the username. */
  avatar: string;
}

export interface ProfileUpdateRequest {
  username?: string;
  avatar?: string;
}

export interface PasswordChangeRequest {
  current_password: string;
  new_password: string;
}

export interface AuthResponse {
  token: string;
  user: AuthUser;
}

export interface RegisterRequest {
  username: string;
  // Mandatory: the account is confirmed by email, so there is no signup without one.
  email: string;
  password: string;
  password_confirm: string;
}

/** Registration deliberately does NOT log you in: it returns a message, not a token. */
export interface RegisterResponse {
  detail: string;
  email: string;
}

export interface VerifyEmailRequest {
  uid: string;
  token: string;
}

/** Re-opening an already-used link is a success, but yields no new credentials. */
export interface VerifyEmailResponse {
  token?: string;
  user?: AuthUser;
  detail?: string;
  already_active?: boolean;
}

export interface LoginRequest {
  username: string;
  password: string;
}
