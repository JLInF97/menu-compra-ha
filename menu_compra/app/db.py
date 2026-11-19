"""Almacenamiento SQLite transaccional, sin servicios de terceros."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

SCHEMA_VERSION = 4
TABLES = ("categories", "supermarkets", "products", "price_history", "dishes", "dish_ingredients", "menu_entries", "shopping_items")
SEED_CATEGORIES = [
    ("Fruta", 10, 0), ("Verdura y hortalizas", 20, 0), ("Carne", 30, 0),
    ("Pescado y marisco", 40, 0), ("Lácteos y huevos", 50, 0),
    ("Panadería", 60, 0), ("Despensa", 70, 0), ("Bebidas", 80, 0),
    ("Limpieza", 90, 0), ("Higiene", 100, 0), ("Otros", 110, 0),
    ("Congelados", 0, 1), ("Sin especificar", 110, 0),
]
SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL COLLATE NOCASE UNIQUE,
 sort_order INTEGER NOT NULL DEFAULT 50 CHECK(sort_order BETWEEN 0 AND 10000),
 is_frozen INTEGER NOT NULL DEFAULT 0 CHECK(is_frozen IN (0,1))
);
CREATE TABLE IF NOT EXISTS supermarkets (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL COLLATE NOCASE UNIQUE
);
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL COLLATE NOCASE,
 category_id INTEGER NOT NULL REFERENCES categories(id),
 supermarket_id INTEGER NOT NULL REFERENCES supermarkets(id),
 unit TEXT NOT NULL DEFAULT 'ud', notes TEXT NOT NULL DEFAULT '',
 price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 0 AND 100000000),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 updated_at TEXT NOT NULL,
 UNIQUE(name,supermarket_id)
);
CREATE TABLE IF NOT EXISTS price_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER NOT NULL REFERENCES products(id),
 supermarket_id INTEGER NOT NULL REFERENCES supermarkets(id),
 price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 0 AND 100000000),
 recorded_at TEXT NOT NULL,
 source TEXT NOT NULL,
 supermarket_name_snapshot TEXT
);
CREATE INDEX IF NOT EXISTS history_product ON price_history(product_id,id);
CREATE TABLE IF NOT EXISTS dishes (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL COLLATE NOCASE UNIQUE,
 notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS dish_ingredients (
 dish_id INTEGER NOT NULL REFERENCES dishes(id) ON DELETE CASCADE,
 product_id INTEGER NOT NULL REFERENCES products(id),
 quantity TEXT NOT NULL,
 PRIMARY KEY(dish_id,product_id)
);
CREATE TABLE IF NOT EXISTS menu_entries (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 date TEXT NOT NULL,
 slot TEXT NOT NULL CHECK(slot IN ('lunch','dinner')),
 text TEXT NOT NULL,
 dish_id INTEGER REFERENCES dishes(id) ON DELETE SET NULL,
 position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0)
);
CREATE TABLE IF NOT EXISTS shopping_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER NOT NULL UNIQUE REFERENCES products(id),
 supermarket_id INTEGER NOT NULL REFERENCES supermarkets(id),
 unit TEXT NOT NULL,
 quantity TEXT NOT NULL,
 checked INTEGER NOT NULL DEFAULT 0 CHECK(checked IN (0,1)),
 note TEXT NOT NULL DEFAULT '',
 unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents BETWEEN 0 AND 100000000)
);
"""


def unicode_nocase(left, right):
    left, right = left.casefold(), right.casefold()
    return (left > right) - (left < right)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sync_shopping_products(connection, product_id=None):
    params = () if product_id is None else (product_id,)
    where = "" if product_id is None else " WHERE product_id=?"
    connection.execute("""UPDATE shopping_items SET
        unit_price_cents=(SELECT price_cents FROM products WHERE id=shopping_items.product_id),
        supermarket_id=(SELECT supermarket_id FROM products WHERE id=shopping_items.product_id),
        unit=(SELECT unit FROM products WHERE id=shopping_items.product_id)""" + where, params)


def ensure_system_metadata(connection):
    """Unificar la categoría genérica antigua sin perder productos ni precios."""
    current = connection.execute("SELECT id FROM categories WHERE name='Sin especificar'").fetchone()
    legacy = connection.execute("SELECT id FROM categories WHERE name='Sin categoría'").fetchone()
    if current is None and legacy is not None:
        connection.execute("UPDATE categories SET name='Sin especificar',sort_order=110,is_frozen=0 WHERE id=?", (legacy[0],))
        category_id = legacy[0]
    elif current is not None:
        category_id = current[0]
        if legacy is not None and legacy[0] != category_id:
            connection.execute("UPDATE products SET category_id=? WHERE category_id=?", (category_id, legacy[0]))
            connection.execute("DELETE FROM categories WHERE id=?", (legacy[0],))
        connection.execute("UPDATE categories SET name='Sin especificar',sort_order=110,is_frozen=0 WHERE id=?", (category_id,))
    else:
        category_id = connection.execute("INSERT INTO categories(name,sort_order,is_frozen) VALUES('Sin especificar',110,0)").lastrowid
    connection.execute("INSERT OR IGNORE INTO supermarkets(name) VALUES('Sin especificar')")
    supermarket_id = connection.execute("SELECT id FROM supermarkets WHERE name='Sin especificar'").fetchone()[0]
    connection.execute("UPDATE supermarkets SET name='Sin especificar' WHERE id=?", (supermarket_id,))
    return category_id, supermarket_id


class Database:
    def __init__(self, directory):
        self.path = Path(directory) / "menu_compra.sqlite3"

    @contextmanager
    def connect(self, write=False):
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.create_collation("NOCASE", unicode_nocase)
        connection.create_function("casefold", 1, str.casefold, deterministic=True)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        connection.execute("PRAGMA busy_timeout = 20000")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            else:
                connection.execute("BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.create_collation("NOCASE", unicode_nocase)
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError("Base de datos de una versión más reciente. No se modificará.")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA secure_delete = ON")
            connection.executescript(SCHEMA)
            connection.execute("BEGIN IMMEDIATE")
            if version == 0:
                connection.executemany("INSERT OR IGNORE INTO categories(name,sort_order,is_frozen) VALUES(?,?,?)", SEED_CATEGORIES)
                connection.execute("INSERT OR IGNORE INTO supermarkets(name) VALUES ('Sin especificar')")
            elif version == 1:
                # Reconstruir solo el menú: conservar IDs y todas las demás tablas.
                connection.execute("""CREATE TABLE menu_entries_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
                    slot TEXT NOT NULL CHECK(slot IN ('lunch','dinner')), text TEXT NOT NULL,
                    dish_id INTEGER REFERENCES dishes(id) ON DELETE SET NULL,
                    position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0))""")
                connection.execute("INSERT INTO menu_entries_v2(id,date,slot,text,dish_id,position) SELECT id,date,slot,text,dish_id,0 FROM menu_entries")
                connection.execute("DROP TABLE menu_entries")
                connection.execute("ALTER TABLE menu_entries_v2 RENAME TO menu_entries")
            connection.execute("CREATE INDEX IF NOT EXISTS menu_day_slot ON menu_entries(date,slot,position,id)")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(price_history)")}
            if "supermarket_name_snapshot" not in columns:
                connection.execute("ALTER TABLE price_history ADD COLUMN supermarket_name_snapshot TEXT")
            # Ya no se archivan productos: conservar los antiguos y hacerlos visibles.
            connection.execute("UPDATE products SET active=1 WHERE active=0")
            ensure_system_metadata(connection)
            sync_shopping_products(connection)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
        finally:
            connection.close()
