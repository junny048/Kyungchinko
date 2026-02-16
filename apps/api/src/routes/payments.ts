import { FastifyPluginAsync } from "fastify";
import { prisma } from "../prisma.js";
import { env } from "../config.js";
import { randomUUID } from "node:crypto";
import { z } from "zod";

const packages = [
  { id: "p1000", krw: 1000, point: 1000 },
  { id: "p5000", krw: 5000, point: 5500 },
  { id: "p10000", krw: 10000, point: 11500 },
];

const createOrderSchema = z.object({ packageId: z.string() });

export const paymentRoutes: FastifyPluginAsync = async (app) => {
  app.get("/shop/packages", async () => ({ packages }));

  app.post("/payments/create-order", { preHandler: [app.authenticate] }, async (request, reply) => {
    const userId = request.user.sub;
    const body = createOrderSchema.parse(request.body);

    const pkg = packages.find((p) => p.id === body.packageId);
    if (!pkg) return reply.code(400).send({ message: "Invalid package" });

    const orderId = `order_${randomUUID()}`;
    const payment = await prisma.payment.create({
      data: {
        userId,
        provider: "ETC",
        orderId,
        amountKRW: pkg.krw,
        pointGranted: BigInt(pkg.point),
        status: "CREATED",
      },
    });

    return {
      orderId,
      paymentId: payment.id,
      provider: payment.provider,
      sandboxCheckoutUrl: `/mock-checkout?orderId=${orderId}`,
    };
  });

  app.post("/payments/webhook/:provider", async (request, reply) => {
    const rawProvider = (request.params as { provider: string }).provider.toUpperCase();
    const provider = z.enum(["TOSS", "IMPORT", "ETC"]).safeParse(rawProvider);
    if (!provider.success) return reply.code(400).send({ message: "Unsupported provider" });
    const signature = request.headers["x-webhook-signature"];

    if (signature !== env.WEBHOOK_SHARED_SECRET) {
      return reply.code(401).send({ message: "Invalid signature" });
    }

    const body = z.object({
      orderId: z.string(),
      status: z.enum(["PAID", "FAILED", "CANCELED", "REFUNDED"]),
      raw: z.any().optional(),
    }).parse(request.body);

    const payment = await prisma.payment.findUnique({ where: { orderId: body.orderId } });
    if (!payment) return reply.code(404).send({ message: "Order not found" });

    if (payment.status === "PAID") return { ok: true, idempotent: true };

    if (body.status === "PAID") {
      await prisma.$transaction(async (tx) => {
        await tx.payment.update({
          where: { id: payment.id },
          data: { status: "PAID", paidAt: new Date(), rawJson: body.raw ?? null, provider: provider.data },
        });

        await tx.wallet.update({
          where: { userId: payment.userId },
          data: { balancePoint: { increment: payment.pointGranted } },
        });

        await tx.walletTransaction.create({
          data: {
            userId: payment.userId,
            type: "CHARGE",
            amount: payment.pointGranted,
            refType: "PAYMENT",
            refId: payment.id,
            metaJson: { orderId: payment.orderId, provider },
          },
        });
      });
    } else {
      await prisma.payment.update({
        where: { id: payment.id },
        data: { status: body.status, rawJson: body.raw ?? null, provider: provider.data },
      });
    }

    return { ok: true };
  });
};
