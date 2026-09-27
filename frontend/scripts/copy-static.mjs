import { cp, mkdir, readdir, rm, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repository = resolve(frontend, "..");
const source = join(frontend, "dist");
const target = join(repository, "service", "static");

// Проверяем источник до замены статики. Путь назначения фиксирован в проекте.
await stat(join(source, "index.html"));
await stat(join(repository, "service", "Dockerfile"));
await mkdir(target, { recursive: true });
for (const entry of await readdir(target)) {
  if (entry !== ".gitkeep") await rm(join(target, entry), { recursive: true, force: true });
}
for (const entry of await readdir(source)) {
  await cp(join(source, entry), join(target, entry), { recursive: true });
}
console.log("Готовая сборка опубликована в service/static/ для Docker и локального API.");
