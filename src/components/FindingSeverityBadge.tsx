import { Badge } from "@/components/ui/badge";
import { AlertTriangle, AlertCircle, Info } from "lucide-react";

interface FindingSeverityBadgeProps {
  severity: "critical" | "warning" | "info";
}

export default function FindingSeverityBadge({ severity }: FindingSeverityBadgeProps) {
  switch (severity) {
    case "critical":
      return (
        <Badge variant="critical">
          <AlertCircle className="size-3" />
          Critical
        </Badge>
      );
    case "warning":
      return (
        <Badge variant="warning">
          <AlertTriangle className="size-3" />
          Warning
        </Badge>
      );
    case "info":
      return (
        <Badge variant="info">
          <Info className="size-3" />
          Info
        </Badge>
      );
  }
}
