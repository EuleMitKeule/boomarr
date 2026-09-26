import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AuthState } from "@/lib/types";

export const AUTH_QUERY = ["auth"] as const;

export function useAuthState() {
  return useQuery({
    queryKey: AUTH_QUERY,
    queryFn: () => api.get<AuthState>("auth/state"),
    staleTime: 30_000,
  });
}
