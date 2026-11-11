import fs from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";

const root = "C:/Users/User/Documents/ChatGPT/Taraz-design";
const sourceDir = path.join(root, "assets/presentation/source/poster-drafts");
const outputDir = path.join(root, "assets/presentation/posters");
const montagePath = path.join(root, "output/OquMap_Hackathon_Pitch_montage.png");
const names = [
  "slide-01-cover",
  "slide-02-problem",
  "slide-03-atlas",
  "slide-04-sign-flip",
  "slide-05-critic",
  "slide-06-constraints",
  "slide-07-fidelity",
  "slide-08-dataset",
  "slide-09-architecture",
  "slide-10-demo",
];

await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(path.dirname(montagePath), { recursive: true });

const prepared = [];
for (const name of names) {
  const input = path.join(sourceDir, `${name}.png`);
  const output = path.join(outputDir, `${name}-16x9.png`);
  await sharp(input)
    .resize(1920, 1080, { fit: "cover", position: "north" })
    .png({ compressionLevel: 9 })
    .toFile(output);
  prepared.push(output);
}

const thumbs = await Promise.all(
  prepared.map((file) => sharp(file).resize(384, 216).png().toBuffer()),
);
await sharp({
  create: { width: 1960, height: 462, channels: 4, background: "#17191F" },
})
  .composite(thumbs.map((input, i) => ({
    input,
    left: 10 + (i % 5) * 390,
    top: 10 + Math.floor(i / 5) * 226,
  })))
  .png({ compressionLevel: 9 })
  .toFile(montagePath);

console.log(montagePath);
