"""Importa os CSVs originais para SQLite. Usa somente a biblioteca padrao.

Execute na raiz do projeto: python app/import_data.py
Valores monetarios sao armazenados em centavos. Reexecucoes atualizam por ID.
"""

import csv
import json
import sqlite3
import sys
from contextlib import closing
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
DATABASE_PATH = DATA_DIR / "store.sqlite3"
FILE_PREFIX = "desafio_tecnico_ai_eng - "

# A ordem respeita as dependencias entre as tabelas.
# Colunas dos CSVs sao mantidas, exceto os valores BRL convertidos para centavos.
TABLES = {
    "categories": {
        "columns": "category_id name description".split(),
        "keys": ("category_id",),
        "schema": """category_id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                     description TEXT""",
    },
    "customers": {
        "columns": "customer_id name phone email city".split(),
        "keys": ("customer_id",),
        "schema": """customer_id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                     phone TEXT, email TEXT, city TEXT""",
    },
    "products": {
        "columns": "product_id price_brl name category_id description stock_quantity status specs created_at".split(),
        "keys": ("product_id",),
        "schema": """product_id INTEGER PRIMARY KEY,
                     price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
                     name TEXT NOT NULL,
                     category_id INTEGER NOT NULL REFERENCES categories(category_id),
                     description TEXT,
                     stock_quantity INTEGER NOT NULL CHECK(stock_quantity >= 0),
                     status TEXT NOT NULL CHECK(status IN ('active','discontinued','coming_soon')),
                     specs TEXT, created_at TEXT""",
    },
    "orders": {
        "columns": "order_id customer_id order_date status total_brl payment_method tracking_code estimated_delivery notes".split(),
        "keys": ("order_id",),
        "schema": """order_id INTEGER PRIMARY KEY,
                     customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
                     order_date TEXT NOT NULL,
                     status TEXT NOT NULL CHECK(status IN ('delivered','shipped','confirmed','pending','cancelled')),
                     total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
                     payment_method TEXT, tracking_code TEXT,
                     estimated_delivery TEXT, notes TEXT""",
    },
    "order_items": {
        "columns": "order_id quantity product_id".split(),
        "keys": ("order_id", "product_id"),
        "schema": """order_id INTEGER NOT NULL REFERENCES orders(order_id),
                     quantity INTEGER NOT NULL CHECK(quantity > 0),
                     product_id INTEGER NOT NULL REFERENCES products(product_id),
                     PRIMARY KEY(order_id, product_id)""",
    },
    "promotions": {
        "columns": "promotion_id product_id discount_percent description is_active".split(),
        "keys": ("promotion_id",),
        "schema": """promotion_id INTEGER PRIMARY KEY,
                     product_id INTEGER NOT NULL REFERENCES products(product_id),
                     discount_percent INTEGER NOT NULL CHECK(discount_percent BETWEEN 0 AND 100),
                     description TEXT,
                     is_active INTEGER NOT NULL CHECK(is_active IN (0, 1))""",
    },
}

MONEY_COLUMNS = {"price_brl": "price_cents", "total_brl": "total_cents"}
INTEGER_COLUMNS = {
    "category_id", "customer_id", "product_id", "order_id", "promotion_id",
    "quantity", "stock_quantity", "discount_percent", "is_active",
}
DATE_COLUMNS = {"order_date", "estimated_delivery", "created_at"}


def convert_value(column, value):
    """Converte sem usar float. Campos vazios viram NULL no SQLite."""
    if value is None or value.strip() == "":
        return None
    if column in MONEY_COLUMNS:
        try:
            cents = Decimal(value.strip()) * 100
        except InvalidOperation as exc:
            raise ValueError("valor monetario invalido") from exc
        if not cents.is_finite() or cents < 0 or cents != cents.to_integral_value():
            raise ValueError("valor monetario precisa ser nao negativo e ter no maximo duas casas")
        return int(cents)
    if column in INTEGER_COLUMNS:
        return int(value.strip())
    if column in DATE_COLUMNS:
        return date.fromisoformat(value.strip()).isoformat()
    if column == "specs":
        if not isinstance(json.loads(value), dict):
            raise ValueError("specs deve conter um objeto JSON")
    return value


def read_table(data_dir, table, spec):
    path = data_dir / f"{FILE_PREFIX}{table}.csv"
    records = []
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if (reader.fieldnames is None
                or len(reader.fieldnames) != len(spec["columns"])
                or set(reader.fieldnames) != set(spec["columns"])):
            raise ValueError(f"{path.name}: cabecalho diferente do esperado")
        for row in reader:
            line = reader.line_num
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path.name}, linha {line}: numero incorreto de campos")
            converted = {}
            for column in spec["columns"]:
                try:
                    converted[column] = convert_value(column, row[column])
                except (ValueError, InvalidOperation) as exc:
                    # Nao incluir valores pessoais no diagnostico.
                    raise ValueError(f"{path.name}, linha {line}: campo {column} invalido") from exc
            key = tuple(converted[column] for column in spec["keys"])
            if any(value is None for value in key):
                raise ValueError(f"{path.name}, linha {line}: identificador ausente")
            if key in seen:
                raise ValueError(f"{path.name}, linha {line}: identificador duplicado")
            seen.add(key)
            records.append(tuple(converted[column] for column in spec["columns"]))
    return records


def import_data(data_dir=DATA_DIR, database_path=DATABASE_PATH):
    """Atualiza os dados por chave numa transacao unica.

    Nao apaga registros ausentes de CSVs futuros. Os seis arquivos representam
    a base inicial do desafio. Uma futura sincronizacao completa exige outra regra.
    """
    data_dir, database_path = Path(data_dir), Path(database_path)
    # Validar todos os arquivos antes de abrir ou modificar o banco.
    source = {
        table: read_table(data_dir, table, spec)
        for table, spec in TABLES.items()
    }
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            # Inclui criacao das tabelas e insercoes na mesma transacao.
            connection.execute("BEGIN")
            for table, spec in TABLES.items():
                connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({spec['schema']})")
                columns = [MONEY_COLUMNS.get(c, c) for c in spec["columns"]]
                placeholders = ", ".join("?" for _ in columns)
                updates = ", ".join(
                    f"{column} = excluded.{column}"
                    for column in columns if column not in spec["keys"]
                )
                # Identificadores SQL sao constantes deste arquivo. Dados usam parametros.
                sql = (
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
                    f"ON CONFLICT ({', '.join(spec['keys'])}) DO UPDATE SET {updates}"
                )
                connection.executemany(sql, source[table])
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("relacoes invalidas entre as tabelas")
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TABLES
        }


def main():
    try:
        counts = import_data()
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Falha na importacao: {exc}", file=sys.stderr)
        return 1
    print(f"Importacao concluida: {DATABASE_PATH}")
    for table, count in counts.items():
        print(f"{table}: {count} registros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
