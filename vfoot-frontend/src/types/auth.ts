export interface AuthUser {
  id: number;
  username: string;
  email: string;
}

export interface AuthResponse {
  token: string;
  user: AuthUser;
}

export interface RegisterRequest {
  username: string;
  email?: string;
  password: string;
  password_confirm: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}
