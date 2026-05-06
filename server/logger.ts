import pino from "pino";

export const logger = pino({
  level: process.env.LOG_LEVEL || "info",
  transport: {
    target: "pino-pretty",
    options: { colorize: true },
  },
});

export function requestLogger(
  req: import("express").Request,
  res: import("express").Response,
  next: import("express").NextFunction,
) {
  const start = Date.now();
  res.on("finish", () => {
    const event = {
      method: req.method,
      path: req.path,
      status: res.statusCode,
      elapsedMs: Date.now() - start,
    };
    if (res.statusCode >= 500) logger.error(event, "request failed");
    else if (res.statusCode >= 400) logger.warn(event, "request error");
    else logger.info(event, "request");
  });
  next();
}
