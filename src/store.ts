import { create } from "zustand";
import { Section, Entity } from "./types";
import { apiLogin, apiMe, setAccessToken } from "./services/api";

type State = {
  section: Section;
  selectedEntity: Entity | null;
  sidebarCollapsed: boolean;
  loginComplete: boolean;
  alertFilter: "ALL" | "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  userName: string | null;
  userRole: string | null;
  loginError: string | null;
  loggingIn: boolean;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
  enterApp: () => void;
  setSection: (section: Section) => void;
  setSelectedEntity: (entity: Entity | null) => void;
  toggleSidebar: () => void;
  setAlertFilter: (filter: State["alertFilter"]) => void;
};

export const useAppStore = create<State>((set, get) => ({
  section: "login",
  selectedEntity: null,
  sidebarCollapsed: true,
  loginComplete: false,
  alertFilter: "ALL",
  userName: null,
  userRole: null,
  loginError: null,
  loggingIn: false,
  setSection: (section) => set({ section }),
  setSelectedEntity: (s) => set({ selectedEntity: s }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  enterApp: () => set({ section: "command-center", loginComplete: true, loginError: null }),
  setAlertFilter: (alertFilter) => set({ alertFilter }),
  login: async (username, password) => {
    set({ loggingIn: true, loginError: null });
    try {
      const tokens = await apiLogin(username, password);
      setAccessToken(tokens.access_token);
      const user = await apiMe();
      set({
        userName: user.full_name ?? user.username,
        userRole: user.role,
        section: "command-center",
        loginComplete: true,
        loggingIn: false,
        loginError: null,
      });
      return true;
    } catch (err) {
      setAccessToken(null);
      set({
        loggingIn: false,
        loginError: err instanceof Error ? err.message : "Login failed",
      });
      return false;
    }
  },
  logout: () => {
    setAccessToken(null);
    set({ loginComplete: false, section: "login", userName: null, userRole: null });
  },
}));
