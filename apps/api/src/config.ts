import "dotenv/config";
import { z } from "zod";

const envSchema = z.object({
  DATABASE_URL: z.string().min(1),
  REDIS_URL: z.string().min(1),
  JWT_ACCESS_SECRET: z.string().min(16),
  JWT_REFRESH_SECRET: z.string().min(16),
  WEBHOOK_SHARED_SECRET: z.string().min(1),
  PORT: z.coerce.number().default(4000),
});

export const env = envSchema.parse(process.env);

