import { ChevronRight, Home } from "lucide-react";
import type { PathSegment } from "@/types";

interface BreadcrumbsProps {
  segments: PathSegment[];
  onNavigate: (path: string) => void;
}

export default function Breadcrumbs({ segments, onNavigate }: BreadcrumbsProps) {
  return (
    <nav className="flex items-center gap-1 text-sm text-muted-foreground overflow-x-auto">
      {segments.map((seg, i) => (
        <span key={seg.path} className="flex items-center gap-1 shrink-0">
          {i > 0 && <ChevronRight className="size-3.5" />}
          <button
            onClick={() => onNavigate(seg.path)}
            className={`hover:text-foreground transition-colors ${
              i === segments.length - 1 ? "text-foreground font-medium" : ""
            }`}
          >
            {i === 0 ? <Home className="size-3.5" /> : seg.name}
          </button>
        </span>
      ))}
    </nav>
  );
}
