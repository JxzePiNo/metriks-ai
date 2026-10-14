import Link from "next/link";
import { Logo } from "./Logo";
import { MobileMenu } from "./MobileMenu";
import { NavLinks, type NavItem } from "./NavLinks";
import { FOCUS_RING } from "./styles";

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Home" },
  { href: "/dashboard", label: "Dashboard" },
];

export function SiteHeader() {
  return (
    <header className="relative border-b border-slate-200 bg-white">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Logo />
        <nav aria-label="Main" className="hidden md:block">
          <NavLinks items={NAV_ITEMS} />
        </nav>
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard"
            className={`hidden rounded-md bg-indigo-600 px-3.5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 sm:inline-block ${FOCUS_RING}`}
          >
            Open dashboard
          </Link>
          <MobileMenu items={NAV_ITEMS} />
        </div>
      </div>
    </header>
  );
}
