import { FastifyPluginAsync } from "fastify";
import { prisma } from "../prisma.js";
import { weightedPick } from "../utils/weighted-pick.js";
import { RewardRarity } from "@prisma/client";
import { z } from "zod";
import { redis } from "../redis.js";

const spinSchema = z.object({
  idempotencyKey: z.string().min(8).max(100),
  useTicket: z.boolean().optional().default(false),
});

async function enforceRateLimit(userId: string): Promise<void> {
  if (redis.status !== "ready") return;
  const now = Math.floor(Date.now() / 1000);
  const secKey = `rl:spin:sec:${userId}:${now}`;
  const minKey = `rl:spin:min:${userId}:${Math.floor(now / 60)}`;

  const secCount = await redis.incr(secKey);
  if (secCount === 1) await redis.expire(secKey, 2);
  if (secCount > 3) throw new Error("Too many spins per second");

  const minCount = await redis.incr(minKey);
  if (minCount === 1) await redis.expire(minKey, 70);
  if (minCount > 60) throw new Error("Too many spins per minute");
}

export const machineRoutes: FastifyPluginAsync = async (app) => {
  app.get("/machines", async () => {
    return prisma.machine.findMany({
      where: { isActive: true },
      select: {
        id: true,
        name: true,
        themeKey: true,
        costPerSpin: true,
        ticketAllowed: true,
        isActive: true,
      },
      orderBy: { createdAt: "desc" },
    });
  });

  app.get("/machines/:id", async (request, reply) => {
    const { id } = request.params as { id: string };
    const machine = await prisma.machine.findUnique({
      where: { id },
      include: {
        currentProbabilityVersion: {
          include: {
            rarityWeights: true,
            rewardPoolItems: { include: { rewardCatalog: true } },
          },
        },
      },
    });

    if (!machine || !machine.isActive) return reply.code(404).send({ message: "Machine not found" });
    return machine;
  });

  app.post("/machines/:id/spin", { preHandler: [app.authenticate] }, async (request, reply) => {
    const userId = request.user.sub;
    const { id: machineId } = request.params as { id: string };
    const body = spinSchema.parse(request.body);

    try {
      await enforceRateLimit(userId);
    } catch (err) {
      return reply.code(429).send({ message: (err as Error).message });
    }

    const spin = await prisma.$transaction(async (tx) => {
      const existing = await tx.spin.findUnique({
        where: { userId_idempotencyKey: { userId, idempotencyKey: body.idempotencyKey } },
        include: { resultRewardCatalog: true },
      });
      if (existing) {
        const wallet = await tx.wallet.findUnique({ where: { userId } });
        return {
          spinId: existing.id,
          idempotentReplay: true,
          result: {
            rarity: existing.resultRarity,
            reward: existing.resultRewardCatalog,
          },
          balancePoint: wallet?.balancePoint ?? BigInt(0),
          ticketBalance: wallet?.ticketBalance ?? 0,
          inventoryDelta: { rewardCatalogId: existing.resultRewardCatalogId, qty: 0 },
        };
      }

      const machine = await tx.machine.findUnique({
        where: { id: machineId },
        include: {
          currentProbabilityVersion: {
            include: {
              rarityWeights: true,
              rewardPoolItems: { include: { rewardCatalog: true } },
            },
          },
        },
      });

      if (!machine || !machine.isActive || !machine.currentProbabilityVersion) {
        throw new Error("Machine unavailable");
      }

      if (body.useTicket && !machine.ticketAllowed) {
        throw new Error("This machine does not allow tickets");
      }

      if (body.useTicket) {
        const ticketResult = await tx.wallet.updateMany({
          where: { userId, ticketBalance: { gte: 1 } },
          data: { ticketBalance: { decrement: 1 } },
        });
        if (ticketResult.count !== 1) throw new Error("Insufficient tickets");
      } else {
        const pointResult = await tx.wallet.updateMany({
          where: { userId, balancePoint: { gte: BigInt(machine.costPerSpin) } },
          data: { balancePoint: { decrement: BigInt(machine.costPerSpin) } },
        });
        if (pointResult.count !== 1) throw new Error("Insufficient points");
      }

      const pickedRarity = weightedPick(
        machine.currentProbabilityVersion.rarityWeights.map((rw) => ({ item: rw.rarity, weight: rw.weight })),
      );

      const pool = machine.currentProbabilityVersion.rewardPoolItems.filter((it) => it.rarity === pickedRarity);
      if (!pool.length) throw new Error("Broken reward pool config");

      const pickedReward = weightedPick(pool.map((p) => ({ item: p.rewardCatalog, weight: p.weight })));

      let deltaQty = 1;
      const existingInventory = await tx.inventory.findUnique({
        where: { userId_rewardCatalogId: { userId, rewardCatalogId: pickedReward.id } },
      });

      if (existingInventory) {
        if (pickedReward.stackable) {
          await tx.inventory.update({
            where: { id: existingInventory.id },
            data: { qty: { increment: 1 } },
          });
        } else {
          await tx.wallet.update({
            where: { userId },
            data: { balancePoint: { increment: BigInt(5) } },
          });
          await tx.walletTransaction.create({
            data: {
              userId,
              type: "REWARD",
              amount: BigInt(5),
              refType: "SPIN",
              refId: body.idempotencyKey,
              metaJson: { reason: "duplicate_non_stackable_to_dust", rewardCatalogId: pickedReward.id },
            },
          });
          deltaQty = 0;
        }
      } else {
        await tx.inventory.create({
          data: {
            userId,
            rewardCatalogId: pickedReward.id,
            qty: 1,
          },
        });
      }

      const newSpin = await tx.spin.create({
        data: {
          userId,
          machineId,
          costPoint: body.useTicket ? 0 : machine.costPerSpin,
          usedTicket: body.useTicket,
          probabilityVersionId: machine.currentProbabilityVersion.id,
          resultRarity: pickedRarity as RewardRarity,
          resultRewardCatalogId: pickedReward.id,
          idempotencyKey: body.idempotencyKey,
        },
      });

      await tx.walletTransaction.create({
        data: {
          userId,
          type: "SPEND",
          amount: body.useTicket ? BigInt(0) : BigInt(-machine.costPerSpin),
          refType: "SPIN",
          refId: newSpin.id,
          metaJson: { usedTicket: body.useTicket },
        },
      });

      const wallet = await tx.wallet.findUniqueOrThrow({ where: { userId } });

      return {
        spinId: newSpin.id,
        idempotentReplay: false,
        result: {
          rarity: pickedRarity,
          reward: pickedReward,
        },
        balancePoint: wallet.balancePoint,
        ticketBalance: wallet.ticketBalance,
        inventoryDelta: { rewardCatalogId: pickedReward.id, qty: deltaQty },
      };
    });

    return spin;
  });
};
