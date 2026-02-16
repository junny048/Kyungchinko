import { FastifyPluginAsync } from "fastify";
import { prisma } from "../prisma.js";

function dayKey(date = new Date()): string {
  return date.toISOString().slice(0, 10);
}

export const eventRoutes: FastifyPluginAsync = async (app) => {
  app.post("/events/daily-checkin", { preHandler: [app.authenticate] }, async (request, reply) => {
    const userId = request.user.sub;
    const key = dayKey();
    const refId = `daily-checkin:${key}`;

    const exists = await prisma.walletTransaction.findFirst({
      where: { userId, refType: "EVENT", refId },
    });

    if (exists) return reply.code(409).send({ message: "Already checked in today" });

    await prisma.$transaction(async (tx) => {
      await tx.wallet.update({
        where: { userId },
        data: { ticketBalance: { increment: 1 } },
      });

      await tx.walletTransaction.create({
        data: {
          userId,
          type: "REWARD",
          amount: BigInt(0),
          refType: "EVENT",
          refId,
          metaJson: { reward: "ticket", qty: 1 },
        },
      });
    });

    return { ok: true, ticketGranted: 1 };
  });

  app.get("/events/status", { preHandler: [app.authenticate] }, async (request) => {
    const userId = request.user.sub;
    const key = dayKey();
    const refId = `daily-checkin:${key}`;

    const checkedIn = Boolean(
      await prisma.walletTransaction.findFirst({
        where: { userId, refType: "EVENT", refId },
        select: { id: true },
      }),
    );

    return { dailyCheckin: { date: key, checkedIn } };
  });
};
