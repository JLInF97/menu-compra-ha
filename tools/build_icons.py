"""Derivados del icono aprobado. No genera ni redibuja el diseño."""
from pathlib import Path
from hashlib import sha256
import json


from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / 'artwork' / 'icono-maestro.png'


def main():
    if not MASTER.is_file():
        raise FileNotFoundError('Falta artwork/icono-maestro.png: recupera el maestro aprobado del proyecto.')
    image = Image.open(MASTER).convert('RGBA')
    assert image.width == image.height
    folder = ROOT / 'menu_compra/app/static/icons'
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for size in (32, 180, 192, 512):
        target = folder / f'icon-{size}.png'
        image.resize((size, size), Image.Resampling.LANCZOS).save(target, optimize=True)
        files.append(target)
    icon = ROOT / 'menu_compra/icon.png'
    image.resize((128,128), Image.Resampling.LANCZOS).save(icon, optimize=True)
    files.append(icon)
    favicon = ROOT / 'menu_compra/app/static/favicon.ico'
    image.resize((256,256), Image.Resampling.LANCZOS).save(favicon, format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64)])
    files.append(favicon)
    logo = Image.new('RGBA', (512,160), (0,0,0,0))
    thumbnail = image.resize((140,140), Image.Resampling.LANCZOS)
    logo.alpha_composite(thumbnail, (8,10))
    # Letras ya rasterizadas: conserva exactamente el diseño sin instalar fuentes.
    with Image.open(ROOT / 'artwork' / 'logotipo-texto.png') as lettering:
        assert lettering.size == (344,160)
        logo.alpha_composite(lettering.convert('RGBA'), (168,0))
    logo_path = ROOT / 'menu_compra/logo.png'
    logo.save(logo_path, optimize=True)
    files.append(logo_path)

    for path in files:
        with Image.open(path) as asset:
            asset.verify()
    print(json.dumps({'master':str(MASTER),'master_sha256':sha256(MASTER.read_bytes()).hexdigest(),
                      'assets':[str(p.relative_to(ROOT)) for p in files]},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
