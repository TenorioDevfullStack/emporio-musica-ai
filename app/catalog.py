"""Consultas de catalogo em SQLite, sem dependencias externas.

Execute na raiz: python app/catalog.py --category violao --max-price 1000
Nesta etapa os precos sao os de tabela. Promocoes serao integradas depois.
"""

import argparse
import json
import sqlite3
import unicodedata
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "store.sqlite3"
CATEGORY_ALIASES = {
    "violao": "violoes", "guitarra": "guitarras", "baixo": "baixos",
    "bateria": "baterias", "teclado": "teclados", "piano": "pianos",
    "ukulele": "ukuleles",
}
SELECT_PRODUCT = """
    SELECT p.product_id, p.name, p.description, p.price_cents,
           p.stock_quantity, p.status, p.specs, p.category_id,
           c.name AS category_name
    FROM products AS p JOIN categories AS c ON c.category_id = p.category_id
"""


def normalize(text):
    """Permite busca sem diferenciar maiusculas ou acentos."""
    return "".join(
        char for char in unicodedata.normalize("NFKD", str(text or "")).casefold()
        if not unicodedata.combining(char)
    ).strip()


def connect_catalog(database_path):
    path = Path(database_path).resolve()
    if not path.is_file():
        raise FileNotFoundError("Banco ausente. Execute primeiro: python app/import_data.py")
    # mode=ro impede a criacao acidental de um banco vazio e qualquer escrita.
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.create_function("normalize", 1, normalize, deterministic=True)
    return connection


def serialize_product(row):
    product = dict(row)
    status, stock = product["status"], product["stock_quantity"]
    product["available"] = status == "active" and stock > 0
    product["availability_reason"] = (
        "available" if product["available"] else
        "out_of_stock" if status == "active" else status
    )
    product["price_brl"] = format(Decimal(product["price_cents"]) / 100, ".2f")
    product["price_basis"] = "catalog_table"
    product["specs"] = json.loads(product["specs"]) if product["specs"] else None
    return product


def search_products(query=None, category=None, max_price_cents=None,
                    available_only=True, limit=10, database_path=DATABASE_PATH):
    """Retorna resultados limitados e a contagem total que atende aos filtros.

    Preco maximo em centavos, inclusivo. A busca padrao oferece apenas itens
    ativos com estoque positivo. Os dados refletem a base fornecida no desafio.
    """
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit deve ser inteiro entre 1 e 50")
    if type(available_only) is not bool:
        raise ValueError("available_only deve ser booleano")
    if max_price_cents is not None and (
        type(max_price_cents) is not int or max_price_cents < 0
    ):
        raise ValueError("max_price_cents deve ser inteiro nao negativo")
    if query is not None and not isinstance(query, str):
        raise ValueError("query deve ser texto")
    if category is not None and not isinstance(category, str):
        raise ValueError("category deve ser texto")
    clauses, params = [], []
    if available_only:
        clauses.extend(["p.status = 'active'", "p.stock_quantity > 0"])
    if query and query.strip():
        for token in normalize(query).split():
            clauses.append("instr(normalize(p.name || ' ' || coalesce(p.description, '')), ?) > 0")
            params.append(token)
    if category and category.strip():
        term = normalize(category)
        clauses.append("instr(normalize(c.name), ?) > 0")
        params.append(CATEGORY_ALIASES.get(term, term))
    if max_price_cents is not None:
        clauses.append("p.price_cents <= ?")
        params.append(max_price_cents)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(connect_catalog(database_path)) as connection:
        total = connection.execute(
            "SELECT count(*) FROM products p JOIN categories c ON c.category_id = p.category_id" + where,
            params,
        ).fetchone()[0]
        rows = connection.execute(
            SELECT_PRODUCT + where + " ORDER BY p.price_cents, p.product_id LIMIT ?",
            [*params, limit],
        ).fetchall()
    return {
        "items": [serialize_product(row) for row in rows],
        "total_matches": total,
        "has_more": total > len(rows),
        "price_basis": "catalog_table",
    }


def get_product(product_id, database_path=DATABASE_PATH):
    """Consulta por ID mesmo quando o produto nao esta disponivel para compra."""
    if type(product_id) is not int or product_id <= 0:
        raise ValueError("product_id deve ser inteiro positivo")
    with closing(connect_catalog(database_path)) as connection:
        row = connection.execute(
            SELECT_PRODUCT + " WHERE p.product_id = ?", (product_id,)
        ).fetchone()
    return serialize_product(row) if row is not None else None


def parse_brl(value):
    try:
        cents = Decimal(value.replace(",", ".")) * 100
    except InvalidOperation as exc:
        raise ValueError("preco invalido; use, por exemplo, 1000 ou 999.90") from exc
    if not cents.is_finite() or cents < 0 or cents != cents.to_integral_value():
        raise ValueError("preco deve ser nao negativo e ter no maximo duas casas decimais")
    return int(cents)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", help="Nome ou palavras da descricao")
    parser.add_argument("--category", help="Categoria; por exemplo, violao")
    parser.add_argument("--max-price", help="Preco de tabela maximo em reais")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--id", type=int, help="Consultar um produto pelo ID")
    parser.add_argument("--include-unavailable", action="store_true")
    args = parser.parse_args()
    try:
        if args.id is not None:
            if (args.query or args.category or args.max_price is not None
                    or args.include_unavailable or args.limit != 10):
                raise ValueError("Use --id sozinho, sem filtros de busca")
            result = get_product(args.id)
        else:
            maximum = parse_brl(args.max_price) if args.max_price is not None else None
            result = search_products(
                query=args.query, category=args.category, max_price_cents=maximum,
                available_only=not args.include_unavailable, limit=args.limit,
            )
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Falha na consulta: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
