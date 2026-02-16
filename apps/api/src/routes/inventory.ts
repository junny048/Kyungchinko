import { FastifyPluginAsync } from "fastify";
import { prisma } from "../prisma.js";
import { z } from "zod";

const equipSchema = z.object({
  slotKey: z.string().min(2),
  rewardCatalogId: z.string().uuid(),
});

export const inventoryRoutes: FastifyPluginAsync = async (app) => {
  app.get("/inventory", { preHandler: [app.authenticate] }, async (request) => {
    const userId = request.user.sub;
    const q = request.query as { rarity?: string; type?: string; cursor?: string };

    const items = await prisma.inventory.findMany({
      where: {
        userId,
        rewardCatalog: {
          ...(q.rarity ? { rarity: q.rarity as never } : {}),
          ...(q.type ? { type: q.type as never } : {}),
        },
      },
      include: { rewardCatalog: true },
      orderBy: { obtainedAt: "desc" },
      take: 30,
      ...(q.cursor ? { skip: 1, cursor: { id: q.cursor } } : {}),
    });

    return {
      items,
      nextCursor: items.length === 30 ? items[items.length - 1]!.id : null,
    };
  });

  app.post("/inventory/equip", { preHandler: [app.authenticate] }, async (request, reply) => {
    const userId = request.user.sub;
    const body = equipSchema.parse(request.body);

    const inventory = await prisma.inventory.findUnique({
      where: { userId_rewardCatalogId: { userId, rewardCatalogId: body.rewardCatalogId } },
      include: { rewardCatalog: true },
    });
    if (!inventory || inventory.qty < 1) return reply.code(400).send({ message: "Item not owned" });

    const equip = await prisma.equip.upsert({
      where: { userId_slotKey: { userId, slotKey: body.slotKey } },
      update: { rewardCatalogId: body.rewardCatalogId },
      create: { userId, slotKey: body.slotKey, rewardCatalogId: body.rewardCatalogId },
      include: { rewardCatalog: true },
    });

    return equip;
  });

  app.get("/profile/equip", { preHandler: [app.authenticate] }, async (request) => {
    const userId = request.user.sub;
    return prisma.equip.findMany({ where: { userId }, include: { rewardCatalog: true } });
  });
};
