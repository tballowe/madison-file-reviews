import { useState } from "react";
import { ChevronRight, Folder, FolderOpen } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { fetchFolderListing } from "@/lib/api";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface FolderTreeProps {
  currentPath: string;
  onNavigate: (path: string) => void;
}

interface TreeNodeProps {
  name: string;
  path: string;
  currentPath: string;
  depth: number;
  onNavigate: (path: string) => void;
}

function TreeNode({ name, path, currentPath, depth, onNavigate }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(false);
  const isActive = currentPath === path;

  const { data } = useQuery({
    queryKey: ["folders", path],
    queryFn: () => fetchFolderListing(path),
    enabled: expanded,
  });

  const subfolders = data?.items.filter((i) => i.type === "directory") || [];

  return (
    <div>
      <button
        onClick={() => {
          onNavigate(path);
          setExpanded(!expanded);
        }}
        className={cn(
          "flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-sm hover:bg-accent transition-colors",
          isActive && "bg-accent font-medium",
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <ChevronRight
          className={cn(
            "size-3.5 shrink-0 transition-transform",
            expanded && "rotate-90",
          )}
        />
        {expanded ? (
          <FolderOpen className="size-4 shrink-0 text-amber-500" />
        ) : (
          <Folder className="size-4 shrink-0 text-amber-500" />
        )}
        <span className="truncate">{name}</span>
      </button>
      {expanded &&
        subfolders.map((folder) => (
          <TreeNode
            key={folder.path}
            name={folder.display_name}
            path={folder.path}
            currentPath={currentPath}
            depth={depth + 1}
            onNavigate={onNavigate}
          />
        ))}
    </div>
  );
}

export default function FolderTree({ currentPath, onNavigate }: FolderTreeProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["folders", "/"],
    queryFn: () => fetchFolderListing("/"),
  });

  const rootFolders = data?.items.filter((i) => i.type === "directory") || [];

  return (
    <ScrollArea className="h-full">
      <div className="p-2">
        <div className="mb-2 px-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Directories
        </div>
        {isLoading && (
          <div className="px-2 py-4 text-sm text-muted-foreground">Loading...</div>
        )}
        {rootFolders.map((folder) => (
          <TreeNode
            key={folder.path}
            name={folder.display_name}
            path={folder.path}
            currentPath={currentPath}
            depth={0}
            onNavigate={onNavigate}
          />
        ))}
      </div>
    </ScrollArea>
  );
}
