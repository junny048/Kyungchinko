import { PrismaClient, PaymentProvider, ProbabilityStatus, RewardRarity, RewardType } from "@prisma/client";

const prisma = new PrismaClient();

async function main() {
  const admin = await prisma.user.upsert({
    where: { email: "admin@example.com" },
    update: {},
    create: {
      email: "admin@example.com",
      passwordHash: "$2a$10$1TgPAca95j4ZZQ8uUUxJx.PG6T4JUA4eehke92U4kMsewQhLlnUzW",
      role: "ADMIN",
      wallet: { create: { balancePoint: BigInt(100000), ticketBalance: 10 } },
    },
  });

  const user = await prisma.user.upsert({
    where: { email: "user@example.com" },
    update: {},
    create: {
      email: "user@example.com",
      passwordHash: "$2a$10$1TgPAca95j4ZZQ8uUUxJx.PG6T4JUA4eehke92U4kMsewQhLlnUzW",
      wallet: { create: { balancePoint: BigInt(10000), ticketBalance: 3 } },
    },
  });

  const rewards = await Promise.all([
    prisma.rewardCatalog.create({ data: { name: "Common Dust", type: RewardType.CURRENCY, rarity: RewardRarity.COMMON, stackable: true } }).catch(() => null),
    prisma.rewardCatalog.create({ data: { name: "Rare Badge", type: RewardType.COSMETIC, rarity: RewardRarity.RARE, stackable: false } }).catch(() => null),
    prisma.rewardCatalog.create({ data: { name: "Epic Frame", type: RewardType.COSMETIC, rarity: RewardRarity.EPIC, stackable: false } }).catch(() => null),
    prisma.rewardCatalog.create({ data: { name: "Legendary Aura", type: RewardType.COSMETIC, rarity: RewardRarity.LEGENDARY, stackable: false } }).catch(() => null),
  ]);

  const existing = await prisma.machine.findFirst({ where: { name: "Starter Machine" } });
  if (existing) return;

  const machine = await prisma.machine.create({
    data: { name: "Starter Machine", themeKey: "starter", costPerSpin: 100, ticketAllowed: true },
  });

  const version = await prisma.probabilityVersion.create({
    data: {
      machineId: machine.id,
      versionNumber: 1,
      status: ProbabilityStatus.PUBLISHED,
      note: "Initial version",
      publishedAt: new Date(),
      rarityWeights: {
        create: [
          { rarity: RewardRarity.COMMON, weight: 8000 },
          { rarity: RewardRarity.RARE, weight: 1700 },
          { rarity: RewardRarity.EPIC, weight: 280 },
          { rarity: RewardRarity.LEGENDARY, weight: 20 },
        ],
      },
    },
  });

  await prisma.machine.update({ where: { id: machine.id }, data: { currentProbabilityVersionId: version.id } });

  const rewardByRarity = new Map(rewards.filter(Boolean).map((r) => [r!.rarity, r!]));
  for (const rarity of [RewardRarity.COMMON, RewardRarity.RARE, RewardRarity.EPIC, RewardRarity.LEGENDARY]) {
    const reward = rewardByRarity.get(rarity);
    if (!reward) continue;
    await prisma.rewardPoolItem.create({
      data: {
        probabilityVersionId: version.id,
        rarity,
        rewardCatalogId: reward.id,
        weight: 1,
      },
    });
  }

  await prisma.payment.create({
    data: {
      userId: user.id,
      provider: PaymentProvider.ETC,
      orderId: "seed-order-1",
      amountKRW: 1000,
      pointGranted: BigInt(1000),
      status: "CREATED",
    },
  }).catch(() => null);

  console.log({ admin: admin.email, user: user.email });
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
