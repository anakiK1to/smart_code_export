import json
from pathlib import Path
from typing import Dict, List, Optional
import questionary
import asyncio
import logging
import logging.config
import os
import mimetypes

# Настройка логирования
logging.config.fileConfig('logging.ini')
logger = logging.getLogger(__name__)

# Константы
CONFIG_FILE = Path.home() / ".code_export_configs.json"
DEFAULT_SCAN_DIRS = ["~/projects", "~/Dev", "~/work", "~/code"]

# Дефолтные настройки
DEFAULT_CONFIGS = {
    "stacks": {
        "React + TypeScript (Vite)": {
            "extensions": [".ts", ".tsx", ".js", ".jsx", ".css", ".scss", ".html", ".json"],
            "exclude_dirs": ["node_modules", "dist", ".git", ".vite"],
            "signature_files": ["vite.config.ts", "package.json"],
            "projects": {}
        },
        "Python (Django)": {
            "extensions": [".py", ".html", ".css", ".js"],
            "exclude_dirs": ["venv", "__pycache__", ".git"],
            "signature_files": ["manage.py", "requirements.txt"],
            "projects": {}
        }
    },
    "scan_dirs": DEFAULT_SCAN_DIRS
}

# --- Вспомогательные функции ---
async def show_menu(title: str, choices: List[Dict], back_text: Optional[str] = None) -> Optional[str]:
    """Универсальное меню с опцией возврата"""
    if not choices and not back_text:
        print("⚠️ Нет доступных опций")
        return None

    menu_choices = choices.copy()
    if back_text:
        menu_choices.append({"name": back_text, "value": None})

    try:
        result = await questionary.select(
            title,
            choices=menu_choices,
            qmark=">",
            pointer="→"
        ).ask_async()
        return result
    except Exception as e:
        logger.error(f"Ошибка в меню: {e}")
        return None

def load_configs() -> Dict:
    """Загружает конфиги из файла"""
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIGS
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Ошибка загрузки конфига: {e}")
        return DEFAULT_CONFIGS

def save_configs(configs: Dict) -> None:
    """Сохраняет конфиги в файл"""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(configs, f, indent=2, ensure_ascii=False)
        logger.info("Конфиг успешно сохранен")
    except IOError as e:
        logger.error(f"Ошибка сохранения конфига: {e}")

def detect_stack(project_path: Path, configs: Dict) -> Optional[str]:
    """Определяет стек проекта"""
    project_path = project_path.resolve()
    for stack_name, stack_config in configs["stacks"].items():
        for sig_file in stack_config.get("signature_files", []):
            if (project_path / sig_file).exists():
                return stack_name
    return None

def find_projects(configs: Dict) -> Dict[str, Dict[str, str]]:
    """Автопоиск проектов"""
    found_projects = {}
    for base_dir in configs.get("scan_dirs", DEFAULT_SCAN_DIRS):
        expanded_dir = Path(base_dir).expanduser().resolve()
        if not expanded_dir.exists():
            continue

        for item in expanded_dir.iterdir():
            if item.is_dir():
                stack_name = detect_stack(item, configs)
                if stack_name:
                    found_projects.setdefault(stack_name, {})[item.name] = str(item)
    return found_projects

def build_project_tree(project_path: Path, extensions: List[str], exclude_dirs: List[str], max_depth: int = None) -> List[Dict]:
    """Строит дерево папок и файлов проекта с учетом расширений и исключаемых директорий"""
    project_path = project_path.resolve()
    tree = []

    def scan_directory(path: Path, depth: int = 0) -> List[Dict]:
        items = []
        try:
            for item in sorted(path.iterdir()):  # Сортировка для предсказуемого порядка
                if item.name.lower() in [d.lower() for d in exclude_dirs]:
                    continue
                relative_path = str(item.relative_to(project_path))
                if item.is_dir():
                    if max_depth is not None and depth >= max_depth:
                        continue
                    items.append({
                        "name": f"📁 {relative_path}/",
                        "value": {"type": "directory", "path": str(item), "relative": relative_path}
                    })
                    items.extend(scan_directory(item, depth + 1))
                elif item.is_file and any(item.name.lower().endswith(ext.lower()) for ext in extensions):
                    mime_type, _ = mimetypes.guess_type(item)
                    if mime_type and mime_type.startswith('text'):
                        items.append({
                            "name": f"📄 {relative_path}",
                            "value": {"type": "file", "path": str(item), "relative": relative_path}
                        })
        except Exception as e:
            logger.warning(f"Ошибка при сканировании {path}: {e}")
        return items

    tree = scan_directory(project_path)
    return tree

def export_project_code(project_path: str, extensions: List[str], exclude_dirs: List[str], output_file: str, selected_paths: List[str] = None, max_depth: int = None) -> bool:
    """Экспорт кода проекта с учетом выбранных путей и уровня вложенности"""
    project_path = Path(project_path).resolve()
    output_path = Path(output_file).resolve()
    skipped_files = []
    included_files = []
    MAX_LINES_PER_FILE = 1000
    MAX_FILE_SIZE = 1_000_000  # 1MB

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for root, dirs, files in os.walk(project_path):
                logger.debug(f"Исходные директории: {dirs}")
                dirs[:] = [d for d in dirs if d.lower() not in [ed.lower() for ed in exclude_dirs]]
                logger.debug(f"Обрабатывается директория: {root}")
                logger.debug(f"Директории после фильтрации: {dirs}")

                # Проверка уровня вложенности
                relative_root = Path(root).relative_to(project_path)
                current_depth = len(relative_root.parts)
                if max_depth is not None and current_depth > max_depth:
                    continue

                for file in files:
                    file_path = Path(root) / file
                    relative_path = file_path.relative_to(project_path)

                    # Проверка выбранных путей
                    if selected_paths and str(relative_path) not in selected_paths:
                        continue

                    # Проверка размера файла
                    if file_path.stat().st_size > MAX_FILE_SIZE:
                        logger.warning(f"Пропущен файл из-за большого размера: {relative_path}")
                        skipped_files.append(str(relative_path))
                        continue

                    # Проверка типа файла
                    mime_type, _ = mimetypes.guess_type(file_path)
                    if mime_type and not mime_type.startswith('text'):
                        logger.warning(f"Пропущен файл (не текстовый): {relative_path}")
                        skipped_files.append(str(relative_path))
                        continue

                    if any(file.lower().endswith(ext.lower()) for ext in extensions):
                        logger.info(f"Обработка файла: {relative_path}")
                        try:
                            with file_path.open("r", encoding="utf-8") as code_file:
                                content = code_file.read()
                                content_lines = content.splitlines()
                                if len(content_lines) > MAX_LINES_PER_FILE:
                                    logger.warning(f"Файл {relative_path} обрезан до {MAX_LINES_PER_FILE} строк")
                                    content = '\n'.join(content_lines[:MAX_LINES_PER_FILE])
                                f.write(f"\n=== {relative_path} ===\n\n{content}\n")
                                included_files.append(str(relative_path))
                        except UnicodeDecodeError:
                            try:
                                with file_path.open("r", encoding="latin1", errors="ignore") as code_file:
                                    content = code_file.read()
                                    content_lines = content.splitlines()
                                    if len(content_lines) > MAX_LINES_PER_FILE:
                                        logger.warning(f"Файл {relative_path} обрезан до {MAX_LINES_PER_FILE} строк")
                                        content = '\n'.join(content_lines[:MAX_LINES_PER_FILE])
                                    f.write(f"\n=== {relative_path} ===\n\n{content}\n")
                                    included_files.append(str(relative_path))
                                    logger.warning(f"Файл {relative_path} прочитан с кодировкой latin1")
                            except Exception as e:
                                logger.warning(f"Пропущен файл из-за ошибки кодировки: {relative_path}: {e}")
                                skipped_files.append(str(relative_path))
                        except Exception as e:
                            logger.warning(f"Ошибка чтения файла {relative_path}: {e}")
                            skipped_files.append(str(relative_path))
                    else:
                        logger.debug(f"Пропущен файл (не соответствует расширениям): {relative_path}")
                        skipped_files.append(str(relative_path))

        if skipped_files:
            logger.info(f"Пропущено файлов: {len(skipped_files)}")
            logger.debug(f"Пропущенные файлы: {', '.join(skipped_files)}")
        logger.info(f"Включено файлов: {len(included_files)}")
        logger.debug(f"Включенные файлы: {', '.join(included_files)}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при экспорте: {e}")
        return False

# --- Основные функции ---
async def create_new_stack(configs: Dict) -> Dict:
    """Создание нового стека"""
    try:
        name = await questionary.text(
            "Название стека:",
            validate=lambda x: x.strip() != "" and x not in configs["stacks"]
        ).ask_async()
        if not name:
            return configs

        extensions = await questionary.text(
            "Расширения файлов через пробел:",
            default=".py .html .js .css"
        ).ask_async()
        if not extensions:
            return configs

        exclude_dirs = await questionary.text(
            "Папки для исключения через пробел:",
            default="node_modules .git"
        ).ask_async()
        if not exclude_dirs:
            return configs

        signature_files = await questionary.text(
            "Сигнатурные файлы через пробел:",
            default="package.json"
        ).ask_async()
        if not signature_files:
            return configs

        configs["stacks"][name] = {
            "extensions": extensions.split(),
            "exclude_dirs": exclude_dirs.split(),
            "signature_files": signature_files.split(),
            "projects": {}
        }
        save_configs(configs)
        print(f"✅ Стек '{name}' создан")
        return configs
    except Exception as e:
        logger.error(f"Ошибка при создании стека: {e}")
        return configs

async def edit_stack_config(configs: Dict, stack_name: str) -> Dict:
    """Редактирование конфигурации стека"""
    try:
        current_config = configs["stacks"][stack_name]
        
        extensions = await questionary.text(
            "Расширения файлов через пробел:",
            default=" ".join(current_config["extensions"])
        ).ask_async()
        if extensions:
            current_config["extensions"] = extensions.split()

        exclude_dirs = await questionary.text(
            "Папки для исключения через пробел:",
            default=" ".join(current_config["exclude_dirs"])
        ).ask_async()
        if exclude_dirs:
            current_config["exclude_dirs"] = exclude_dirs.split()

        signature_files = await questionary.text(
            "Сигнатурные файлы через пробел:",
            default=" ".join(current_config["signature_files"])
        ).ask_async()
        if signature_files:
            current_config["signature_files"] = signature_files.split()

        save_configs(configs)
        print(f"✅ Конфигурация стека '{stack_name}' обновлена")
        return configs
    except Exception as e:
        logger.error(f"Ошибка при редактировании конфигурации стека: {e}")
        return configs

async def edit_stack(configs: Dict, stack_name: str) -> Dict:
    """Редактирование стека (проекты и конфигурация)"""
    while True:
        action = await show_menu(
            f"📁 Управление стеком ({stack_name}):",
            choices=[
                {"name": "Редактировать конфигурацию стека", "value": "edit_config"},
                {"name": "Добавить проект", "value": "add"},
                {"name": "Удалить проект", "value": "remove"},
                {"name": "Сканировать папки", "value": "scan"}
            ],
            back_text="← Назад"
        )
        if action is None:
            break

        if action == "edit_config":
            configs = await edit_stack_config(configs, stack_name)

        elif action == "add":
            try:
                project_name = await questionary.text(
                    "Название проекта:",
                    validate=lambda x: x.strip() != "" and x not in configs["stacks"][stack_name]["projects"]
                ).ask_async()
                if not project_name:
                    continue

                project_path = await questionary.path(
                    "Путь к проекту:",
                    only_directories=True,
                    validate=lambda x: Path(x).is_dir()
                ).ask_async()
                if not project_path:
                    continue

                configs["stacks"][stack_name]["projects"][project_name] = str(Path(project_path).resolve())
                save_configs(configs)
                print(f"✅ Проект '{project_name}' добавлен")
            except Exception as e:
                logger.error(f"Ошибка при добавлении проекта: {e}")

        elif action == "remove":
            if not configs["stacks"][stack_name]["projects"]:
                print("⚠️ Нет проектов для удаления")
                continue

            project = await show_menu(
                "Выберите проект для удаления:",
                choices=[{"name": k, "value": k} for k in configs["stacks"][stack_name]["projects"]],
                back_text="← Назад"
            )
            if project is None:
                continue

            del configs["stacks"][stack_name]["projects"][project]
            save_configs(configs)
            print(f"✅ Проект '{project}' удален")

        elif action == "scan":
            found = find_projects(configs)
            if stack_name in found:
                count = 0
                for name, path in found[stack_name].items():
                    if name not in configs["stacks"][stack_name]["projects"]:
                        configs["stacks"][stack_name]["projects"][name] = path
                        count += 1
                save_configs(configs)
                print(f"✅ Добавлено {count} проектов")
            else:
                print("⚠️ Новые проекты не найдены")
    return configs

async def configure_scan_dirs(configs: Dict) -> Dict:
    """Настройка папок для сканирования"""
    try:
        current_dirs = " ".join(configs.get("scan_dirs", DEFAULT_SCAN_DIRS))
        new_dirs = await questionary.text(
            "Укажите папки для сканирования через пробел:",
            default=current_dirs
        ).ask_async()
        
        if new_dirs is None:
            return configs

        scan_dirs = [str(Path(d).expanduser().resolve()) for d in new_dirs.split()]
        valid_dirs = [d for d in scan_dirs if Path(d).exists()]
        
        if len(valid_dirs) < len(scan_dirs):
            invalid_dirs = set(scan_dirs) - set(valid_dirs)
            print(f"⚠️ Пропущены несуществующие папки: {', '.join(invalid_dirs)}")
        
        configs["scan_dirs"] = valid_dirs if valid_dirs else DEFAULT_SCAN_DIRS
        save_configs(configs)
        print("✅ Папки для сканирования обновлены")
        return configs
    except Exception as e:
        logger.error(f"Ошибка при настройке папок: {e}")
        return configs

async def export_flow(configs: Dict) -> None:
    """Процесс экспорта кода с выбором структуры и уровня вложенности"""
    while True:
        stack_name = await show_menu(
            "📦 Выберите стек:",
            choices=[{"name": k, "value": k} for k in configs["stacks"]],
            back_text="← Назад"
        )
        if stack_name is None:
            break

        if not configs["stacks"][stack_name]["projects"]:
            print("⚠️ В этом стеке нет проектов. Добавьте их через меню управления конфигами.")
            continue

        project_choices = [{"name": k, "value": k} for k in configs["stacks"][stack_name]["projects"]]
        project_choices.append({"name": "Указать путь вручную", "value": None})

        project_name = await show_menu(
            "Выберите проект:",
            choices=project_choices,
            back_text="← Назад к стекам"
        )
        if project_name is None:
            continue

        try:
            if project_name is None:  # Ручной ввод
                project_path = await questionary.path(
                    "Укажите путь к проекту:",
                    only_directories=True,
                    validate=lambda x: Path(x).is_dir()
                ).ask_async()
                if not project_path:
                    continue
            else:
                project_path = configs["stacks"][stack_name]["projects"][project_name]

            # Построение структуры проекта
            tree = build_project_tree(
                Path(project_path),
                configs["stacks"][stack_name]["extensions"],
                configs["stacks"][stack_name]["exclude_dirs"]
            )
            tree.insert(0, {"name": "📁 Весь проект", "value": {"type": "all", "path": str(project_path)}})

            # Выбор папок/файлов для экспорта
            selected_items = await questionary.checkbox(
                "Выберите папки/файлов для экспорта:",
                choices=tree,
                qmark=">",
                pointer="→"
            ).ask_async()

            logger.debug(f"Результат выбора: {selected_items}")

            # Проверка результата выбора
            if selected_items is None or not isinstance(selected_items, list):
                print("⚠️ Выбор отменён или ничего не выбрано")
                continue
            if not selected_items:
                print("⚠️ Не выбраны папки/файлы для экспорта")
                continue

            # Определение выбранных путей
            selected_paths = []
            for item in selected_items:
                logger.debug(f"Обрабатывается выбранный элемент: {item}")
                if item["type"] == "file":
                    selected_paths.append(item["relative"])
                elif item["type"] == "directory":
                    # Добавить все файлы из выбранной директории
                    dir_path = Path(item["path"])
                    exclude_dirs_lower = [d.lower() for d in configs["stacks"][stack_name]["exclude_dirs"]]
                    for root, _, files in os.walk(dir_path):
                        root_path = Path(root)
                        if root_path.name.lower() in exclude_dirs_lower:
                            logger.debug(f"Пропущена директория (исключена): {root}")
                            continue
                        for file in files:
                            file_path = root_path / file
                            if any(file.lower().endswith(ext.lower()) for ext in configs["stacks"][stack_name]["extensions"]):
                                relative_path = str(file_path.relative_to(project_path))
                                selected_paths.append(relative_path)
                                logger.debug(f"Добавлен файл из директории: {relative_path}")
                elif item["type"] == "all":
                    selected_paths = None  # Null означает экспорт всего проекта
                    break

            # Выбор уровня вложенности
            max_depth = await questionary.text(
                "Укажите максимальный уровень вложенности (оставьте пустым для полного экспорта):",
                validate=lambda x: x.strip() == "" or (x.isdigit() and int(x) >= 0),
                default=""
            ).ask_async()
            max_depth = int(max_depth) if max_depth.strip() else None

            output_file = await questionary.text(
                "Имя выходного файла:",
                default="exported_code.txt"
            ).ask_async()
            if not output_file:
                output_file = "exported_code.txt"

            logger.info(f"Выбраны пути для экспорта: {selected_paths if selected_paths else 'Весь проект'}")
            logger.info(f"Максимальный уровень вложенности: {max_depth if max_depth is not None else 'Без ограничений'}")

            if export_project_code(
                project_path,
                configs["stacks"][stack_name]["extensions"],
                configs["stacks"][stack_name]["exclude_dirs"],
                output_file,
                selected_paths,
                max_depth
            ):
                print(f"✅ Код успешно экспортирован в {output_file}")

            if not await questionary.confirm(
                "Хотите экспортировать ещё один проект?",
                default=False
            ).ask_async():
                break
        except Exception as e:
            logger.error(f"Ошибка при экспорте: {str(e)}")
            print(f"⚠️ Произошла ошибка при экспорте: {str(e)}")
            continue

async def main_flow() -> None:
    """Основной рабочий процесс"""
    configs = load_configs()

    while True:
        action = await show_menu(
            "🛠️ Code Export CLI - Главное меню:",
            choices=[
                {"name": "Экспорт кода", "value": "export"},
                {"name": "Управление конфигами", "value": "configs"},
                {"name": "Автопоиск проектов", "value": "discover"},
                {"name": "Настройки сканирования", "value": "scan_dirs"}
            ],
            back_text="🚪 Выход"
        )
        if action is None:
            break

        if action == "export":
            if not configs["stacks"]:
                print("⚠️ Нет доступных стеков. Создайте стек в меню управления конфигами.")
                continue
            await export_flow(configs)

        elif action == "configs":
            while True:
                config_action = await show_menu(
                    "⚙️ Управление конфигами:",
                    choices=[
                        {"name": "Создать новый стек", "value": "new_stack"},
                        {"name": "Редактировать стек", "value": "edit_stack"}
                    ],
                    back_text="← Назад"
                )
                if config_action is None:
                    break

                if config_action == "new_stack":
                    configs = await create_new_stack(configs)
                elif config_action == "edit_stack":
                    stack_name = await show_menu(
                        "Выберите стек для редактирования:",
                        choices=[{"name": k, "value": k} for k in configs["stacks"]],
                        back_text="← Назад"
                    )
                    if stack_name is None:
                        continue
                    configs = await edit_stack(configs, stack_name)

        elif action == "discover":
            found = find_projects(configs)
            total = sum(len(projects) for projects in found.values())
            if found:
                for stack, projects in found.items():
                    if stack not in configs["stacks"]:
                        continue
                    for name, path in projects.items():
                        if name not in configs["stacks"][stack]["projects"]:
                            configs["stacks"][stack]["projects"][name] = path
                save_configs(configs)
                print(f"✅ Найдено и добавлено {total} проектов")
            else:
                print("⚠️ Проекты не найдены")

        elif action == "scan_dirs":
            configs = await configure_scan_dirs(configs)

if __name__ == "__main__":
    try:
        asyncio.run(main_flow())
    except KeyboardInterrupt:
        print("\nℹ Программа завершена пользователем")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}")
        print("⚠️ Произошла критическая ошибка. Подробности в логах.")