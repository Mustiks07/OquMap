import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "C:/Users/User/Documents/ChatGPT/Taraz-design";
const skillDir = "C:/Users/User/.codex/plugins/cache/openai-primary-runtime/presentations/26.1110.11613/skills/presentations";
const runtimePython = "C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";
const posterDir = path.join(workspaceDir, "assets/presentation/posters");
const buildDir = path.join(workspaceDir, ".codex-build/presentation/full-raster-deck");
const previewDir = path.join(buildDir, "previews");
const outputDir = path.join(workspaceDir, "output");
const finalPptx = path.join(outputDir, "OquMap_Hackathon_Pitch_v1.pptx");

const posters = [
  ["slide-01-cover-16x9.png", "OquMap: от результата к проверяемому решению"],
  ["slide-02-problem-16x9.png", "47,1% показывает тему, но не решение"],
  ["slide-03-atlas-16x9.png", "Семь открываемых оснований одного решения"],
  ["slide-04-sign-flip-16x9.png", "Сырая разница −5,3 п.п. меняет знак на +5,2 п.п. после поправки"],
  ["slide-05-critic-16x9.png", "Критик блокирует сырой вывод: причинность не доказана"],
  ["slide-06-constraints-16x9.png", "Хорошая рекомендация умеет отказать: запрос 30 часов при максимуме 20"],
  ["slide-07-fidelity-16x9.png", "Без fidelity вывод недействителен"],
  ["slide-08-dataset-16x9.png", "Воспроизводимый корпус: 46 074 ответа, 0 отклонено"],
  ["slide-09-architecture-16x9.png", "ИИ подключается к аналитике, но не заменяет её"],
  ["slide-10-demo-16x9.png", "Проверьте маршрут сами за 3 минуты"],
];

const speakerNotes = [
  "Открытие, 20 секунд. Школе не нужен ещё один дашборд. Ей нужен путь от слабого результата к решению, которое можно открыть, проверить и пересмотреть. OquMap превращает разрозненные измерения в такой маршрут: с источниками, ограничениями и повторным замером.",
  "47,1% сообщает, где просела тема. Но за цифрой скрыты 802 ученика, 32 класса, конкретные задания, цели программы, страницы пособия и бюджет часов. Главный вопрос методиста не «где красное», а «что менять завтра и на каком основании».",
  "Открываем слабую тему и идём по цепочке: цель программы, диагностическое задание, гипотеза ошибки, источник, страница пособия, текущие часы и честный пробел — решения ещё нет. Каждый узел можно открыть до исходных строк.",
  "В сыром сравнении вариант B отстаёт от A на 5,3 пункта. После стандартизации по входному уровню B связан с преимуществом 5,2 пункта. Знак меняется. Поэтому система не даёт выбирать пособие по красивой, но сырой разнице. Это связь, не доказанная причинность.",
  "Модель помогает сформулировать гипотезу, но не владеет фактами. Аналитик замечает смену знака, эксперт связывает вывод с программой, критик сверяет каждое число с серверными доказательствами. Сырой вывод блокируется.",
  "После анализа решение попадает в песочницу. Перераспределить два часа можно, если баланс сохранён. Запрос 30 часов конфликтует с максимумом 20. Система возвращает причину и ничего не исправляет молча.",
  "После пилота OquMap проверяет не только динамику результата, но и то, была ли интервенция выполнена. При 100% fidelity наблюдаем +9,2 пункта. При 18,75% fidelity даже +3,3 пункта не интерпретируется как оценка метода.",
  "Все числа на демо воспроизводимы. Корпус содержит 384 ученика, 16 классов, 8 школ, 42 задания и 46 074 ответа. Он повторно генерируется с фиксированным seed, проходит строгий импорт без отклонённых строк и проверяется по манифесту.",
  "Граница ответственности ясна. Данные и вычисления остаются в детерминированном серверном контуре. LLM подключается к готовым доказательствам, а критик проверяет факты и ограничения. Без ключа аналитика, Atlas и критик продолжают работать.",
  "Финал, 30 секунд. Сейчас за три минуты мы откроем слабую тему, дойдём до диагностического задания и источника, увидим смену знака после поправки, получим вердикт критика и намеренно запросим невозможные 30 часов. Оцените весь проверяемый маршрут, а не обещание ИИ.",
];

async function imageBytes(file) {
  const data = await fs.readFile(file);
  return data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
}

async function writeBlob(file, blob) {
  await fs.writeFile(file, new Uint8Array(await blob.arrayBuffer()));
}

const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });
for (let i = 0; i < posters.length; i += 1) {
  const [filename, alt] = posters[i];
  const slide = presentation.slides.add();
  slide.images.add({
    blob: await imageBytes(path.join(posterDir, filename)),
    contentType: "image/png",
    alt,
    fit: "cover",
    position: { left: 0, top: 0, width: 1280, height: 720 },
  });
  slide.speakerNotes.text = speakerNotes[i];
}

async function main() {
  await fs.mkdir(previewDir, { recursive: true });
  await fs.mkdir(outputDir, { recursive: true });
  for (const [i, slide] of presentation.slides.items.entries()) {
    const png = await presentation.export({ slide, format: "png", scale: 1 });
    await writeBlob(path.join(previewDir, `slide-${String(i + 1).padStart(2, "0")}.png`), png);
  }
  await writeBlob(
    path.join(buildDir, "OquMap_Hackathon_Pitch_montage.webp"),
    await presentation.export({ format: "webp", montage: true }),
  );
  const draft = path.join(buildDir, "OquMap_Hackathon_Pitch_draft.pptx");
  await (await PresentationFile.exportPptx(presentation)).save(draft);

  if (process.argv.includes("--final")) {
    const { finalizePresentation } = await import(
      pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href
    );
    const stagingDir = path.join(buildDir, ".codex-finalizer");
    await fs.mkdir(stagingDir, { recursive: true });
    const candidatePath = path.join(stagingDir, "candidate.pptx");
    await (await PresentationFile.exportPptx(presentation)).save(candidatePath);
    await finalizePresentation({
      explicitTotalSlideCount: 10,
      requiredNativeTableOwnerSlides: [],
      requiredNativeChartOwnerSlides: [],
      workspaceDir,
      candidatePath,
      finalPath: finalPptx,
      pythonExecutable: runtimePython,
      integrityValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_package_integrity.py"),
      layoutValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_layout_geometry.py"),
      layoutArgs: ["--expected-slide-size-emu", "12192000,6858000"],
      verifyArtifactToolImport: true,
      receiptPath: path.join(stagingDir, "OquMap_Hackathon_Pitch_v1.pptx.validation.json"),
      materializeLiteralChartWorkbooks: false,
    });
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
