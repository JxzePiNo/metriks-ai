import { Logo } from "@/components/Logo";
import { MobileMenu } from "@/components/MobileMenu";
import { NavLinks, type NavItem } from "@/components/NavLinks";

const APP_NAV: NavItem[] = [
  { href: "/dashboard", label: "Documents" },
  { href: "/", label: "Back to site" },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-1 flex-col md:flex-row">
      <aside className="hidden w-60 shrink-0 border-r border-slate-200 bg-white p-4 md:block">
        <div className="mb-6 px-3">
          <Logo />
        </div>
        <nav aria-label="Dashboard">
          <NavLinks items={APP_NAV} orientation="vertical" />
        </nav>
      </aside>
      <div className="relative flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 md:hidden">
        <Logo />
        <MobileMenu items={APP_NAV} />
      </div>
      <main id="main" className="flex-1 p-4 sm:p-8">
        {children}
      </main>
    </div>
  );
}
