import { PropsWithChildren } from "react";
import { TopNav } from "./TopNav";
import { useAppStore } from "../store";

export function Layout({ children }: PropsWithChildren) {
  const section = useAppStore((state) => state.section);
  return (
    <div className={`app-shell ${section === "command-center" ? "command-shell" : ""}`.trim()}>
      <TopNav />
      <main className="app-main">{children}</main>
    </div>
  );
}
