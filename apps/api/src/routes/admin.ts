import { FastifyPluginAsync } from "fastify";
import { prisma } from "../prisma.js";
import { z } from "zod";

const machineSchema = z.object({
  name: z.string().min(2),
  themeKey: z.string().min(2),
  costPerSpin: z.number().int().positive(),
  ticketAllowed: z.boolean().default(false),
  isActive: z.boolean().default(true),
});

export const adminRoutes: FastifyPluginAsync = async (app) => {
  app.addHook("preHandler", app.authenticate);
  app.addHook("preHandler", async (request, reply) => {
    if (!["ADMIN", "OP"].includes(request.authUser.role)) {
      return reply.code(403).send({ message: "Forbidden" });
    }
  });

  app.post("/admin/machines", async (request) => {
    const body = machineSchema.parse(request.body);
    return prisma.machine.create({ data: body });
  });

  app.put("/admin/machines/:id", async (request) => {
    const { id } = request.params as { id: string };
    const body = machineSchema.partial().parse(request.body);
    const machine = await prisma.machine.update({ where: { id }, data: body });
    await prisma.auditLog.create({
      data: {
        actorUserId: request.authUser.sub,
        action: "UPDATE_MACHINE",
        targetType: "Machine",
        targetId: id,
        diffJson: body,
      },
    });
    return machine;
  });

  app.post("/admin/machines/:id/probability-versions", async (request, reply) => {
    const { id: machineId } = request.params as { id: string };
    const body = z.object({
      note: z.string().optional(),
      rarityWeights: z.array(z.object({ rarity: z.enum(["COMMON", "RARE", "EPIC", "LEGENDARY"]), weight: z.number().int().positive() })).min(1),
      poolItems: z.array(z.object({ rarity: z.enum(["COMMON", "RARE", "EPIC", "LEGENDARY"]), rewardCatalogId: z.string().uuid(), weight: z.number().int().positive() })).min(1),
    }).parse(request.body);

    const machine = await prisma.machine.findUnique({ where: { id: machineId } });
    if (!machine) return reply.code(404).send({ message: "Machine not found" });

    const latest = await prisma.probabilityVersion.findFirst({
      where: { machineId },
      orderBy: { versionNumber: "desc" },
    });

    const created = await prisma.probabilityVersion.create({
      data: {
        machineId,
        versionNumber: (latest?.versionNumber ?? 0) + 1,
        note: body.note,
        status: "DRAFT",
        rarityWeights: { create: body.rarityWeights },
        rewardPoolItems: { create: body.poolItems },
      },
      include: { rarityWeights: true, rewardPoolItems: true },
    });

    await prisma.auditLog.create({
      data: {
        actorUserId: request.authUser.sub,
        action: "CREATE_PROBABILITY_VERSION",
        targetType: "ProbabilityVersion",
        targetId: created.id,
        diffJson: body,
      },
    });

    return created;
  });

  app.put("/admin/probability-versions/:id/publish", async (request, reply) => {
    const { id } = request.params as { id: string };
    const version = await prisma.probabilityVersion.findUnique({ where: { id } });
    if (!version) return reply.code(404).send({ message: "Version not found" });

    if (version.status === "PUBLISHED") return { ok: true, alreadyPublished: true };

    await prisma.$transaction(async (tx) => {
      await tx.probabilityVersion.updateMany({
        where: { machineId: version.machineId, status: "PUBLISHED" },
        data: { status: "ARCHIVED" },
      });

      await tx.probabilityVersion.update({
        where: { id },
        data: { status: "PUBLISHED", publishedAt: new Date() },
      });

      await tx.machine.update({
        where: { id: version.machineId },
        data: { currentProbabilityVersionId: id },
      });

      await tx.auditLog.create({
        data: {
          actorUserId: request.authUser.sub,
          action: "PUBLISH_PROBABILITY_VERSION",
          targetType: "ProbabilityVersion",
          targetId: id,
        },
      });
    });

    return { ok: true };
  });

  app.post("/admin/rewards", async (request) => {
    const body = z.object({
      type: z.enum(["COSMETIC", "CURRENCY", "ACCESS", "TICKET"]),
      name: z.string().min(2),
      rarity: z.enum(["COMMON", "RARE", "EPIC", "LEGENDARY"]),
      stackable: z.boolean(),
      metadataJson: z.any().optional(),
    }).parse(request.body);

    return prisma.rewardCatalog.create({ data: body });
  });

  app.put("/admin/rewards/:id", async (request) => {
    const { id } = request.params as { id: string };
    const body = z.object({
      type: z.enum(["COSMETIC", "CURRENCY", "ACCESS", "TICKET"]).optional(),
      name: z.string().min(2).optional(),
      rarity: z.enum(["COMMON", "RARE", "EPIC", "LEGENDARY"]).optional(),
      stackable: z.boolean().optional(),
      metadataJson: z.any().optional(),
    }).parse(request.body);

    return prisma.rewardCatalog.update({ where: { id }, data: body });
  });

  app.get("/admin/users/:id", async (request, reply) => {
    const { id } = request.params as { id: string };
    const user = await prisma.user.findUnique({
      where: { id },
      include: {
        wallet: true,
        payments: { orderBy: { createdAt: "desc" }, take: 20 },
        spins: { orderBy: { createdAt: "desc" }, take: 20 },
        inventory: { include: { rewardCatalog: true }, take: 50 },
      },
    });
    if (!user) return reply.code(404).send({ message: "User not found" });
    return user;
  });

  app.post("/admin/users/:id/adjust-points", async (request) => {
    const { id: userId } = request.params as { id: string };
    const body = z.object({ amount: z.number().int(), reason: z.string().min(2) }).parse(request.body);

    await prisma.$transaction(async (tx) => {
      await tx.wallet.update({
        where: { userId },
        data: { balancePoint: { increment: BigInt(body.amount) } },
      });

      await tx.walletTransaction.create({
        data: {
          userId,
          type: "ADJUST",
          amount: BigInt(body.amount),
          refType: "ADMIN",
          refId: request.authUser.sub,
          metaJson: { reason: body.reason },
        },
      });

      await tx.auditLog.create({
        data: {
          actorUserId: request.authUser.sub,
          action: "ADJUST_POINTS",
          targetType: "User",
          targetId: userId,
          diffJson: body,
        },
      });
    });

    return { ok: true };
  });
};


