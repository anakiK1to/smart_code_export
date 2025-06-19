import os
import json
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Set
import questionary

# Константы
CONFIG_FILE = Path.home() / ".code_export_configs.json"
DEFAULT_SCAN_DIRS = ["~/projects", "~/Dev", "~/work", "~/code"]

# Дефолтные конфиги
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
        },
        "Flutter": {
            "extensions": [".dart", ".yaml", ".md"],
            "exclude_dirs": ["build", ".dart_tool"],
            "signature_files": ["pubspec.yaml"],
            "projects": {}
        }
    },
    "scan_dirs": DEFAULT_SCAN_DIRS
}

# --- Вспомогательные функции ---
def load_configs() -> Dict:
    """Загружает конфиги из файла или возвращает дефолтные"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_CONFIGS

def save_configs(configs: Dict):
    """Сохраняет конфиги в файл"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(configs, f, indent=2, ensure_ascii=False)

def detect_stack(project_path: str, configs: Dict) -> Optional[str]:
    """Определяет стек проекта по сигнатурным файлам"""
    for stack_name, stack_config in configs["stacks"].items():
        for sig_file in stack_config.get("signature_files", []):
            if os.path.exists(os.path.join(project_path, sig_file)):
                return stack_name
    return None

def find_projects(configs: Dict) -> Dict[str, Dict[str, str]]:
    """Автопоиск проектов в указанных папках"""
    found_projects = {}
    for base_dir in configs.get("scan_dirs", DEFAULT_SCAN_DIRS):
        expanded_dir = os.path.expanduser(base_dir)
        if not os.path.exists(expanded_dir):
            continue

        for dir_name in os.listdir(expanded_dir):
            dir_path = os.path.join(expanded_dir, dir_name)
            if os.path.isdir(dir_path):
                stack_name = detect_stack(dir_path, configs)
                if stack_name:
                    if stack_name not in found_projects:
                        found_projects[stack_name] = {}
                    found_projects[stack_name][dir_name] = dir_path
    return found_projects

def export_project_code(project_path: str, extensions: List[str], exclude_dirs: List[str], output_file: str):
    """Экспортирует код проекта в файл"""
    with open(output_file, "w", encoding="utf-8") as f:
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                if any(file.endswith(ext) for ext in extensions):
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, project_path)
                    try:
                        with open(file_path, "r", encoding="utf-8") as code_file:
                            f.write(f"\n=== {relative_path} ===\n\n{code_file.read()}\n")
                    except UnicodeDecodeError:
                        pass

# --- CLI-функции ---
async def create_new_stack(configs: Dict) -> Dict:
    """Создает новый стек технологий"""
    name = await questionary.text("Название стека:", validate=lambda x: len(x) > 0).ask_async()
    extensions = await questionary.text(
        "Расширения файлов через пробел:", 
        default=".py .html .js .css"
    ).ask_async()
    exclude_dirs = await questionary.text(
        "Папки для исключения через пробел:", 
        default="node_modules .git"
    ).ask_async()
    signature_files = await questionary.text(
        "Сигнатурные файлы через пробел:", 
        default="package.json"
    ).ask_async()

    configs["stacks"][name] = {
        "extensions": extensions.split(),
        "exclude_dirs": exclude_dirs.split(),
        "signature_files": signature_files.split(),
        "projects": {}
    }
    save_configs(configs)
    return configs

async def auto_discover_projects(configs: Dict) -> Dict:
    """Автопоиск проектов"""
    found_projects = find_projects(configs)
    for stack_name, projects in found_projects.items():
        for proj_name, proj_path in projects.items():
            configs["stacks"][stack_name]["projects"][proj_name] = proj_path
    save_configs(configs)
    print(f"✅ Найдено проектов: {sum(len(p) for p in found_projects.values())}")
    return configs

async def configure_scan_dirs(configs: Dict) -> Dict:
    """Настройка папок для сканирования"""
    new_dirs = await questionary.text(
        "Укажите папки для сканирования (через пробел):",
        default=" ".join(configs.get("scan_dirs", DEFAULT_SCAN_DIRS))
    ).ask_async()
    configs["scan_dirs"] = new_dirs.split()
    save_configs(configs)
    return configs

async def main():
    configs = load_configs()

    while True:
        action = await questionary.select(
            "🛠️ Code Export CLI - Выберите действие:",
            choices=[
                {"name": "Экспортировать код", "value": "export"},
                {"name": "Управление конфигами", "value": "manage"},
                {"name": "Автопоиск проектов", "value": "discover"},
                {"name": "Настройки сканирования", "value": "scan_dirs"},
                {"name": "Выход", "value": "exit"}
            ]
        ).ask_async()

        if action == "discover":
            configs = await auto_discover_projects(configs)
        elif action == "scan_dirs":
            configs = await configure_scan_dirs(configs)
        elif action == "manage":
            config_action = await questionary.select(
                "Управление конфигами:",
                choices=[
                    {"name": "Создать новый стек", "value": "new_stack"},
                    {"name": "Редактировать проекты в стеке", "value": "edit_stack"},
                    {"name": "Назад", "value": "back"}
                ]
            ).ask_async()
            if config_action == "new_stack":
                configs = await create_new_stack(configs)
            elif config_action == "edit_stack":
                stack_name = await questionary.select(
                    "Выберите стек:",
                    choices=list(configs["stacks"].keys())
                ).ask_async()
                # ... (функция редактирования проектов из предыдущих версий)
        elif action == "export":
            stack_name = await questionary.select(
                "Выберите стек:",
                choices=list(configs["stacks"].keys())
            ).ask_async()
            project_name = await questionary.select(
                "Выберите проект:",
                choices=list(configs["stacks"][stack_name]["projects"].keys()) + ["Ввести путь вручную"],
            ).ask_async()
            if project_name == "Ввести путь вручную":
                project_path = await questionary.path("Путь к проекту:", only_directories=True).ask_async()
            else:
                project_path = configs["stacks"][stack_name]["projects"][project_name]
            output_file = await questionary.text("Имя выходного файла:", default="exported_code.txt").ask_async()
            export_project_code(
                project_path,
                configs["stacks"][stack_name]["extensions"],
                configs["stacks"][stack_name]["exclude_dirs"],
                output_file
            )
            print(f"✅ Код экспортирован в {output_file}")
        else:
            break

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())