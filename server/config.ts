import dotenv from "dotenv";
dotenv.config();

export const config = {
  port: parseInt(process.env.PORT || "3001", 10),
  filesApiKey: process.env.FILES_API_KEY || "",
  filesBaseUrl: process.env.FILES_BASE_URL || "https://app.files.com/api/rest/v1",
  anthropicApiKey: process.env.ANTHROPIC_API_KEY || process.env.CLAUDE_API_KEY || "",
};

export function validateConfig() {
  if (!config.filesApiKey) {
    throw new Error("FILES_API_KEY is required");
  }
  if (!config.anthropicApiKey) {
    throw new Error("ANTHROPIC_API_KEY is required");
  }
}
