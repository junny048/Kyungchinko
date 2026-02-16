import Fastify from "fastify";
import cookie from "@fastify/cookie";
import cors from "@fastify/cors";
import jwt from "@fastify/jwt";
import { env } from "./config.js";
import { authRoutes } from "./routes/auth.js";
import { walletRoutes } from "./routes/wallet.js";
import { paymentRoutes } from "./routes/payments.js";
import { machineRoutes } from "./routes/machines.js";
import { inventoryRoutes } from "./routes/inventory.js";
import { eventRoutes } from "./routes/events.js";
import { adminRoutes } from "./routes/admin.js";
import { redis } from "./redis.js";

const app = Fastify({ logger: true });

await app.register(cors, { origin: true, credentials: true });
await app.register(cookie);
await app.register(jwt, { secret: env.JWT_ACCESS_SECRET });

app.decorate("authenticate", async (request, reply) => {
  try {
    const token = request.headers.authorization?.replace("Bearer ", "");
    if (!token) return reply.code(401).send({ message: "Missing access token" });

    const payload = await request.jwtVerify<{ sub: string; role: "USER" | "ADMIN" | "OP"; email: string; type: string }>({
      onlyCookie: false,
    });
    if (payload.type !== "access") return reply.code(401).send({ message: "Invalid token type" });
    request.user = payload;
  } catch {
    return reply.code(401).send({ message: "Unauthorized" });
  }
});

app.get("/health", async () => ({ ok: true }));

await app.register(async (api) => {
  await api.register(authRoutes, { prefix: "/auth" });
  await api.register(walletRoutes);
  await api.register(paymentRoutes);
  await api.register(machineRoutes);
  await api.register(inventoryRoutes);
  await api.register(eventRoutes);
  await api.register(adminRoutes);
}, { prefix: "/api" });

try {
  await redis.connect();
} catch {
  app.log.warn("Redis unavailable, rate limit disabled until reconnect");
}

await app.listen({ port: env.PORT, host: "0.0.0.0" });
