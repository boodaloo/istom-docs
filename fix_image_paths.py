#!/usr/bin/env python3
"""
Скрипт для обновления путей к изображениям в markdown-файлах документации iStom.

Логика:
1. Читает content_mapping.yaml — маппинг docx -> docs/*.md
2. Строит обратный маппинг: для каждого docs/*.md файла — список исходных docx (по порядку)
3. Для каждого docx определяет папку с изображениями в extracted/
4. Для merged файлов: считает кол-во изображений в каждом converted/*.md
   и назначает диапазоны image1..imageN соответствующим папкам
5. Обновляет ссылки в docs/*.md файлах
"""

import os
import re
import yaml
from pathlib import Path

BASE_DIR = Path("/home/booda/istom/istom-docs")
DOCS_DIR = BASE_DIR / "docs"
EXTRACTED_DIR = DOCS_DIR / "images" / "extracted"
CONVERTED_DIR = BASE_DIR / "converted"
MAPPING_FILE = BASE_DIR / "content_mapping.yaml"
KNOWLEDGE_BASE = Path("/home/booda/istom/knowledge base")


def docx_name_to_folder(docx_name: str) -> str:
    """
    Преобразует имя .docx файла (без расширения) в имя папки extracted/.
    Пробелы и символы ' /\\:*?"<>|,' заменяются на '_'.
    Повторяющиеся '_' сжимаются в один.
    """
    # Убираем расширение .docx если есть
    name = docx_name
    if name.endswith(".docx"):
        name = name[:-5]
    if name.endswith(".md"):
        name = name[:-3]

    # Заменяем спецсимволы на '_'
    special_chars = ' /\\:*?"<>|,'
    result = []
    for ch in name:
        if ch in special_chars:
            result.append("_")
        else:
            result.append(ch)

    folder = "".join(result)
    # Сжимаем повторяющиеся '_' в один
    while "__" in folder:
        folder = folder.replace("__", "_")
    # Убираем ведущий/завершающий '_'
    folder = folder.strip("_")
    return folder


def get_md_name_from_mapping_key(key: str) -> str:
    """
    Из ключа маппинга (может содержать подпапку, например 'касса/файл.md')
    возвращает имя .md файла без расширения для поиска в converted/.
    """
    # Берём basename без расширения
    basename = os.path.basename(key)
    if basename.endswith(".md"):
        return basename[:-3]
    return basename


def get_converted_path(mapping_key: str) -> Path:
    """
    По ключу маппинга находит соответствующий .md файл в converted/.
    Ключ может быть вида 'подпапка/имя файла.md' или просто 'имя файла.md'.
    """
    path = CONVERTED_DIR / mapping_key
    if path.exists():
        return path
    # Пробуем без суффикса подпапки, если путь не найден
    return None


def count_images_in_converted(mapping_key: str) -> int:
    """Считает кол-во ссылок на изображения в converted/*.md файле."""
    path = get_converted_path(mapping_key)
    if path is None or not path.exists():
        return 0
    content = path.read_text(encoding="utf-8")
    return len(re.findall(r"images/media/image\d+\.\w+", content))


def get_relative_prefix(md_file: Path) -> str:
    """
    Вычисляет относительный префикс для пути к изображениям.
    docs/index.md -> "images/extracted/"
    docs/modules/foo.md -> "../images/extracted/"
    docs/modules/finance/bar.md -> "../../images/extracted/"
    """
    # Глубина относительно docs/
    rel = md_file.relative_to(DOCS_DIR)
    depth = len(rel.parts) - 1  # -1 за сам файл
    if depth == 0:
        return "images/extracted/"
    else:
        return "../" * depth + "images/extracted/"


def find_extracted_folder(docx_basename: str) -> str | None:
    """
    По имени docx (без расширения) находит реальную папку в extracted/.
    """
    folder_name = docx_name_to_folder(docx_basename)
    candidate = EXTRACTED_DIR / folder_name
    if candidate.exists():
        return folder_name
    return None


def get_image_count_in_extracted(folder_name: str) -> int:
    """Считает кол-во файлов изображений в папке extracted/folder_name/."""
    folder = EXTRACTED_DIR / folder_name
    if not folder.exists():
        return 0
    return len(list(folder.iterdir()))


def load_mapping():
    """Загружает content_mapping.yaml и возвращает словарь."""
    with open(MAPPING_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_reverse_mapping(mapping: dict) -> dict:
    """
    Строит обратный маппинг: docs/*.md -> list of docx source keys (в порядке маппинга).
    Ключи — строки вида 'docs/путь/к/файлу.md'.
    Значения — список ключей из content_mapping.yaml (строки с именами .md файлов).
    """
    reverse: dict[str, list[str]] = {}
    for category, entries in mapping.items():
        if not isinstance(entries, dict):
            continue
        for source_key, dest_path in entries.items():
            if dest_path == "skip":
                continue
            if dest_path not in reverse:
                reverse[dest_path] = []
            reverse[dest_path].append(source_key)
    return reverse


def get_docx_basename(source_key: str) -> str:
    """
    Из ключа маппинга вида 'подпапка/имя файла.md' или 'имя файла.md'
    возвращает имя docx-файла без расширения.
    """
    basename = os.path.basename(source_key)
    if basename.endswith(".md"):
        return basename[:-3]
    return basename


def build_image_assignment(sources: list[str]) -> list[tuple[str, int, int]]:
    """
    Для списка исходных источников (source_keys) строит список назначений:
    [(folder_name, start_img_num, end_img_num), ...]

    Логика: считаем кол-во изображений в каждом converted/*.md
    и последовательно назначаем диапазоны image номеров.

    Если в extracted папке больше изображений чем в converted — используем
    кол-во из extracted.
    """
    assignments = []
    current_num = 1

    for source_key in sources:
        docx_basename = get_docx_basename(source_key)
        folder_name = find_extracted_folder(docx_basename)

        if folder_name is None:
            # Папки нет в extracted — у этого источника нет изображений
            # но нам всё равно надо знать сколько изображений он добавляет
            count_converted = count_images_in_converted(source_key)
            if count_converted > 0:
                # Изображения есть в converted но папки нет — пропускаем
                assignments.append((None, current_num, current_num + count_converted - 1))
                current_num += count_converted
            # else: нет изображений — пропускаем без изменения счётчика
            continue

        count_converted = count_images_in_converted(source_key)
        count_extracted = get_image_count_in_extracted(folder_name)

        # Берём максимум как реальное количество изображений
        count = max(count_converted, count_extracted)

        if count == 0:
            # Нет изображений у этого источника
            continue

        end_num = current_num + count - 1
        assignments.append((folder_name, current_num, end_num))
        current_num = end_num + 1

    return assignments


def replace_image_links(content: str, assignments: list[tuple], prefix: str) -> tuple[str, int]:
    """
    Заменяет ссылки вида:
      ![...](../../images/media/imageN.png)
      ![...](../images/media/imageN.png)
      ![...](images/media/imageN.png)
    на:
      ![](prefix/FOLDER/imageN.png)

    Возвращает (новый контент, кол-во замен).
    """
    # Строим паттерн для поиска ссылок на изображения
    pattern = re.compile(
        r'!\[([^\]]*)\]\((?:\.\.\/)*images\/media\/(image(\d+)\.[a-zA-Z]+)\)',
        re.IGNORECASE
    )

    replacements = 0

    def replace_match(m):
        nonlocal replacements
        alt_text = m.group(1)
        img_file = m.group(2)  # например, image3.png
        img_num = int(m.group(3))  # номер изображения

        # Находим подходящее назначение по номеру изображения
        target_folder = None
        for folder_name, start, end in assignments:
            if start <= img_num <= end:
                target_folder = folder_name
                break

        if target_folder is None:
            # Не нашли назначение — оставляем как есть
            return m.group(0)

        # Формируем новый путь: внутри папки изображения нумеруются от 1
        # img_num внутри папки = img_num - start + 1
        folder_img_num = img_num - [a[1] for a in assignments if a[0] == target_folder][0] + 1
        new_img_file = f"image{folder_img_num}.png"
        new_path = f"{prefix}{target_folder}/{new_img_file}"
        replacements += 1
        return f"![]({new_path})"

    new_content = pattern.sub(replace_match, content)
    return new_content, replacements


def main():
    print("=== Обновление путей к изображениям в docs/ ===\n")

    # Шаг 1: Загружаем маппинг
    print("Шаг 1: Загружаем content_mapping.yaml...")
    mapping = load_mapping()
    print(f"  Загружено категорий: {len(mapping)}")

    # Шаг 2: Строим обратный маппинг
    print("\nШаг 2: Строим обратный маппинг (docs/*.md -> sources)...")
    reverse_mapping = build_reverse_mapping(mapping)
    print(f"  Целевых .md файлов: {len(reverse_mapping)}")

    # Шаг 3: Для каждого docs/*.md строим назначения изображений
    print("\nШаг 3: Строим назначения изображений...")

    # Статистика
    files_updated = 0
    files_skipped = 0
    total_replacements = 0
    errors = []

    # Собираем все .md файлы в docs/ у которых есть ссылки на изображения
    md_files_with_images = []
    for md_path in DOCS_DIR.rglob("*.md"):
        content = md_path.read_text(encoding="utf-8")
        if re.search(r'images/media/image\d+', content, re.IGNORECASE):
            md_files_with_images.append(md_path)

    print(f"  .md файлов с ссылками на изображения: {len(md_files_with_images)}")

    print("\nШаг 4: Обновляем пути в .md файлах...")
    print("-" * 60)

    for md_path in sorted(md_files_with_images):
        rel_path = md_path.relative_to(BASE_DIR)
        dest_key = str(md_path.relative_to(BASE_DIR))  # вида 'docs/путь/файл.md'

        # Ищем sources для этого файла
        # Ключи в reverse_mapping — строки вида 'docs/путь/к/файлу.md'
        sources = reverse_mapping.get(dest_key, [])

        if not sources:
            errors.append(f"  WARN: {rel_path} — не найден в маппинге")
            # Попробуем угадать по имени файла
            # Просто пропускаем
            files_skipped += 1
            continue

        # Строим назначения
        assignments = build_image_assignment(sources)

        if not assignments:
            errors.append(f"  WARN: {rel_path} — нет папок изображений для источников: {sources}")
            files_skipped += 1
            continue

        # Вычисляем префикс пути
        prefix = get_relative_prefix(md_path)

        # Читаем и заменяем
        content = md_path.read_text(encoding="utf-8")
        new_content, count = replace_image_links(content, assignments, prefix)

        if count > 0:
            md_path.write_text(new_content, encoding="utf-8")
            files_updated += 1
            total_replacements += count
            print(f"  OK: {rel_path}")
            print(f"      Замен: {count}, источники: {[get_docx_basename(s) for s in sources]}")
            for folder, start, end in assignments:
                if folder:
                    print(f"      image{start}..image{end} -> extracted/{folder}/")
        else:
            errors.append(f"  WARN: {rel_path} — паттерн не совпал (замен: 0)")
            files_skipped += 1

    print("\n" + "=" * 60)
    print("=== РЕЗУЛЬТАТ ===")
    print(f"  Файлов обновлено:      {files_updated}")
    print(f"  Ссылок заменено:       {total_replacements}")
    print(f"  Файлов пропущено:      {files_skipped}")

    if errors:
        print(f"\n  Предупреждения/ошибки ({len(errors)}):")
        for e in errors:
            print(e)

    print("\n=== Готово ===")


if __name__ == "__main__":
    main()
