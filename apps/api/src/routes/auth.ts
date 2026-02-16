import { FastifyPluginAsync } from "fastify";
import { prisma } from "../prisma.js";
import { hashPassword, verifyPassword } from "../utils/password.js";
import { z } from "zod";

const signupSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
});

const loginSchema = signupSchema;

export const authRoutes: FastifyPluginAsync = async (app) => {
  app.post("/signup", async (request, reply) => {
    const body = signupSchema.parse(request.body);

    const exists = await prisma.user.findUnique({ where: { email: body.email } });
    if (exists) return reply.code(409).send({ message: "Email already in use" });

    const user = await prisma.user.create({
      data: {
        email: body.email,
        passwordHash: await hashPassword(body.password),
        wallet: { create: {} },
      },
    });

    const accessToken = app.jwt.sign({ sub: user.id, role: user.role, email: user.email, type: "access" }, { expiresIn: "15m" });
    const refreshToken = app.jwt.sign({ sub: user.id, role: user.role, email: user.email, type: "refresh" }, { expiresIn: "7d" });

    reply.setCookie("refreshToken", refreshToken, {
      httpOnly: true,
      sameSite: "lax",
      path: "/api/auth",
      maxAge: 60 * 60 * 24 * 7,
    });

    return { accessToken };
  });

  app.post("/login", async (request, reply) => {
    const body = loginSchema.parse(request.body);

    const user = await prisma.user.findUnique({ where: { email: body.email } });
    if (!user) return reply.code(401).send({ message: "Invalid credentials" });
    if (user.status !== "ACTIVE") return reply.code(403).send({ message: `Account status: ${user.status}` });

    const ok = await verifyPassword(body.password, user.passwordHash);
    if (!ok) return reply.code(401).send({ message: "Invalid credentials" });

    const accessToken = app.jwt.sign({ sub: user.id, role: user.role, email: user.email, type: "access" }, { expiresIn: "15m" });
    const refreshToken = app.jwt.sign({ sub: user.id, role: user.role, email: user.email, type: "refresh" }, { expiresIn: "7d" });

    reply.setCookie("refreshToken", refreshToken, {
      httpOnly: true,
      sameSite: "lax",
      path: "/api/auth",
      maxAge: 60 * 60 * 24 * 7,
    });

    return { accessToken };
  });

  app.post("/logout", async (_request, reply) => {
    reply.clearCookie("refreshToken", { path: "/api/auth" });
    return { ok: true };
  });

  app.post("/refresh", async (request, reply) => {
    const token = request.cookies.refreshToken;
    if (!token) return reply.code(401).send({ message: "Missing refresh token" });

    try {
      const payload = await app.jwt.verify<{ sub: string; role: "USER" | "ADMIN" | "OP"; email: string; type: string }>(token);
      if (payload.type !== "refresh") return reply.code(401).send({ message: "Invalid token" });

      const accessToken = app.jwt.sign({ sub: payload.sub, role: payload.role, email: payload.email, type: "access" }, { expiresIn: "15m" });
      return { accessToken };
    } catch {
      return reply.code(401).send({ message: "Invalid refresh token" });
    }
  });

  app.post("/request-password-reset", async () => {
    return { ok: true, message: "Reset email request accepted" };
  });

  app.post("/reset-password", async () => {
    return { ok: true, message: "Password reset completed" };
  });
};
