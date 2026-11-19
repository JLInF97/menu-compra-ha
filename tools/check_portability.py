"""Rechaza rutas absolutas personales/de Windows en código y configuración activos."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r'[a-z]:[/\\]+(?:users|windows|program files)(?:[/\\\s]|$)', re.IGNORECASE)
SUFFIXES = {'.py', '.js', '.cjs', '.json', '.yaml', '.yml', '.toml', '.cmd'}
FOLDERS = ('menu_compra', 'custom_components', 'tests', 'tools', '.github', 'diseno')


def violations(root=ROOT):
    findings = []
    candidates = [root / 'package.json', root / 'package-lock.json', root / 'pyproject.toml', root / 'iniciar-local.cmd']
    candidates += [file for folder in FOLDERS for file in (root / folder).rglob('*') if file.is_file()]
    for file in sorted(set(candidates)):
        if file.suffix not in SUFFIXES or '__pycache__' in file.parts or not file.is_file():
            continue
        for number, line in enumerate(file.read_text(encoding='utf-8').splitlines(), 1):
            if PATTERN.search(line):
                findings.append(f'{file.relative_to(root).as_posix()}:{number}')
    return findings


def main():
    findings = violations()
    if findings:
        raise SystemExit('Rutas locales no portables: ' + ', '.join(findings))
    print('Portabilidad: sin rutas personales, fuentes Windows ni navegador local obligatorio en código/configuración.')


if __name__ == '__main__':
    main()
