"use client";

import { useState } from "react";
import { NavLinks, type NavItem } from "./NavLinks";
import { FOCUS_RING } from "./styles";

export function MobileMenu({ items }: { items: NavItem[] }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="md:hidden">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="mobile-menu"
        onClick={() => setOpen((v) => !v)}
        className={`rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 ${FOCUS_RING}`}
      >
        {open ? "Close" : "Menu"}
      </button>
      {open && (
        <nav
          id="mobile-menu"
          aria-label="Mobile"
          className="absolute inset-x-0 top-full z-10 border-b border-slate-200 bg-white p-4 shadow-sm"
          onClick={() => setOpen(false)}
        >
          <NavLinks items={items} orientation="vertical" />
        </nav>
      )}
    </div>
  );
}
