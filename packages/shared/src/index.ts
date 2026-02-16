export type ApiResult<T> = {
  ok: boolean;
  data?: T;
  message?: string;
};

export type RewardRarity = "COMMON" | "RARE" | "EPIC" | "LEGENDARY";
