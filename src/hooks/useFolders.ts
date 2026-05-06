import { useQuery } from "@tanstack/react-query";
import { fetchFolderListing, fetchFolderTree } from "@/lib/api";

export function useFolderListing(path: string) {
  return useQuery({
    queryKey: ["folders", path],
    queryFn: () => fetchFolderListing(path),
  });
}

export function useFolderTree(path: string, depth = 2) {
  return useQuery({
    queryKey: ["folder-tree", path, depth],
    queryFn: () => fetchFolderTree(path, depth),
  });
}
