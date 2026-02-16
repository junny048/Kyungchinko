import { FastifyPluginAsync } from "fastify";
import { prisma } from "../prisma.js";

export const walletRoutes: FastifyPluginAsync = async (app) => {
  app.get("/wallet", { preHandler: [app.authenticate] }, async (request) => {
    const userId = request.authUser.sub;
    const wallet = await prisma.wallet.findUnique({ where: { userId } });
    return {
      balancePoint: wallet?.balancePoint ?? BigInt(0),
      ticketBalance: wallet?.ticketBalance ?? 0,
    };
  });

  app.get("/ledger", { preHandler: [app.authenticate] }, async (request) => {
    const userId = request.authUser.sub;
    const cursor = (request.query as { cursor?: string }).cursor;

    const rows = await prisma.walletTransaction.findMany({
      where: { userId },
      orderBy: { createdAt: "desc" },
      take: 20,
      ...(cursor ? { skip: 1, cursor: { id: cursor } } : {}),
    });

    return {
      items: rows,
      nextCursor: rows.length === 20 ? rows[rows.length - 1]!.id : null,
    };
  });
};


