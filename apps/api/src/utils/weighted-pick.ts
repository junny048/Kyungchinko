import { randomInt } from "node:crypto";

export function weightedPick<T>(items: Array<{ item: T; weight: number }>): T {
  const total = items.reduce((acc, cur) => acc + cur.weight, 0);
  if (total <= 0) throw new Error("Invalid weight set");

  const roll = randomInt(total) + 1;
  let cursor = 0;

  for (const entry of items) {
    cursor += entry.weight;
    if (roll <= cursor) return entry.item;
  }

  return items[items.length - 1]!.item;
}

