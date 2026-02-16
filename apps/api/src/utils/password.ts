import bcrypt from "bcryptjs";

export async function hashPassword(raw: string): Promise<string> {
  return bcrypt.hash(raw, 10);
}

export async function verifyPassword(raw: string, hashed: string): Promise<boolean> {
  return bcrypt.compare(raw, hashed);
}
