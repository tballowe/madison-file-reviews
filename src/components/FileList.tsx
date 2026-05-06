import { Folder, FileText, File } from "lucide-react";
import type { FileItem } from "@/types";
import { formatBytes, formatDate } from "@/lib/utils";

interface FileListProps {
  items: FileItem[];
  onNavigate: (path: string) => void;
}

function getFileIcon(item: FileItem) {
  if (item.type === "directory") return <Folder className="size-4 text-amber-500" />;
  if (item.mime_type?.includes("pdf")) return <FileText className="size-4 text-red-500" />;
  return <File className="size-4 text-muted-foreground" />;
}

export default function FileList({ items, onNavigate }: FileListProps) {
  const folders = items.filter((i) => i.type === "directory");
  const files = items.filter((i) => i.type === "file");
  const sorted = [...folders, ...files];

  if (sorted.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
        <Folder className="size-12 mb-3 opacity-30" />
        <p className="text-sm">This folder is empty</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-2 px-3 font-medium">Name</th>
            <th className="py-2 px-3 font-medium w-24">Size</th>
            <th className="py-2 px-3 font-medium w-36">Modified</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((item) => (
            <tr
              key={item.path}
              className="border-b last:border-0 hover:bg-accent/50 transition-colors"
            >
              <td className="py-2 px-3">
                {item.type === "directory" ? (
                  <button
                    onClick={() => onNavigate(item.path)}
                    className="flex items-center gap-2 hover:text-primary transition-colors"
                  >
                    {getFileIcon(item)}
                    <span>{item.display_name}</span>
                  </button>
                ) : (
                  <div className="flex items-center gap-2">
                    {getFileIcon(item)}
                    <span>{item.display_name}</span>
                  </div>
                )}
              </td>
              <td className="py-2 px-3 text-muted-foreground">
                {item.type === "file" ? formatBytes(item.size) : "—"}
              </td>
              <td className="py-2 px-3 text-muted-foreground">
                {formatDate(item.mtime || item.provided_mtime)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-3 py-2 text-xs text-muted-foreground border-t">
        {folders.length} folders, {files.length} files
      </div>
    </div>
  );
}
