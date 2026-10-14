"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { FOCUS_RING } from "./styles";

export interface NavItem {
  href: string;
  label: string;
}

export function NavLinks({
  items,
  orientation = "horizontal",
}: {
  items: NavItem[];
  orientation?: "horizontal" | "vertical";
}) {
  const pathname = usePathname();

  return (
    <ul
      className={
        orientation === "horizontal" ? "flex items-center gap-1" : "space-y-1"
      }
    >
      {items.map((item) => {
        const active = pathname === item.href;
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`block rounded-md px-3 py-2 text-sm font-medium ${FOCUS_RING} ${
                active
                  ? "bg-indigo-50 text-indigo-700"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              }`}
            >
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
