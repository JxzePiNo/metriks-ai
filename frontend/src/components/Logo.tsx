import Link from "next/link";
import { FOCUS_RING } from "./styles";

export function Logo() {
  return (
    <Link
      href="/"
      className={`flex items-center gap-2 rounded-md font-semibold tracking-tight text-slate-900 ${FOCUS_RING}`}
    >
      <span
        aria-hidden="true"
        className="flex h-7 w-7 items-center justify-center rounded-md bg-indigo-600 text-sm font-bold text-white"
      >
        M
      </span>
      Metriks AI
    </Link>
  );
}
