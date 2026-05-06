import { FileSearch } from "lucide-react";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur">
        <div className="flex h-14 items-center gap-3 px-6">
          <FileSearch className="size-5 text-primary" />
          <h1 className="text-lg font-semibold">Madison File Reviews</h1>
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}
