"""Ejecuta regresión y enlace automático con fixtures explícitas, sin tocar HA."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = (
    ('regresion', 'browser_v5_1.js', 'navegador.json', 'success', False),
    ('conexion-ha', 'browser_v6.js', 'conexion-ha.json', 'passed', False),
    ('branding', 'browser_icon_v1.js', 'branding.json', 'success', False),
    ('enlace-automatico', 'browser_auto_setup.js', 'enlace-automatico.json', 'passed', True),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-dir', type=Path, default=ROOT / 'menu_compra')
    parser.add_argument('--output', type=Path, default=ROOT / 'build' / 'browser-evidence')
    args = parser.parse_args()
    summaries = []
    args.output.mkdir(parents=True, exist_ok=True)
    for name, script, report, passed_key, supervisor_fixture in SCENARIOS:
        evidence = args.output / name
        subprocess.run([sys.executable, str(ROOT / 'tools' / 'verify_ui_v5_1.py'),
                        '--app-dir', str(args.app_dir.resolve()),
                        '--script', str(ROOT / 'tests' / script), '--output', str(evidence.resolve()),
                        *(['--supervisor-fixture'] if supervisor_fixture else [])], check=True)
        result = json.loads((evidence / report).read_text(encoding='utf-8'))
        if not result.get(passed_key) or not result.get('cases') or any(
                result.get(key) for key in ('errors', 'failedResponses', 'pageErrors')):
            raise RuntimeError('Escenario incompleto o fallido: ' + name)
        summaries.append({'scenario': name, 'passed': True, 'checks': len(result['cases']),
                          'supervisor_fixture': supervisor_fixture})
    result = {'success': True, 'checks': sum(row['checks'] for row in summaries), 'scenarios': summaries,
              'real_backend': True, 'real_home_assistant': False}
    (args.output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
