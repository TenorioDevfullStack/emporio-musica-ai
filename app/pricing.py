"""Cotacao de uma unidade: promocao ativa OU 5% no PIX, sem acumular.

Execute na raiz: python app/pricing.py --id 127 --payment pix
Busca com preco final: python app/pricing.py --category ukulele --max-price 500
O preco final e arredondado para centavos, com meio centavo para cima.
A vigencia segue is_active na base fornecida, sem inferir datas pela descricao.
"""

import argparse
import json
import sqlite3
from contextlib import closing

if __package__:
    from .catalog import (
        DATABASE_PATH, CATEGORY_ALIASES, SELECT_PRODUCT, connect_catalog,
        normalize, parse_brl, serialize_product,
    )
else:
    from catalog import (
        DATABASE_PATH, CATEGORY_ALIASES, SELECT_PRODUCT, connect_catalog,
        normalize, parse_brl, serialize_product,
    )


POLICY_SOURCE = {
    "document": "políticas_da_loja.pdf",
    "sections": ["3. Formas de Pagamento", "6.2 Regras de Promoções"],
    "pages": [3, 6],
}


def discounted_cents(original_cents, percent):
    """Arredonda o preco final, nao o desconto, sem usar float."""
    if type(original_cents) is not int or original_cents < 0:
        raise ValueError("preco deve ser inteiro nao negativo em centavos")
    if type(percent) is not int or not 0 <= percent <= 100:
        raise ValueError("percentual deve ser inteiro de 0 a 100")
    return (original_cents * (100 - percent) + 50) // 100


def brl(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def _quote(product, promotions, payment_method):
    """Regra unica de preco, compartilhada pela cotacao e pela busca."""
    result = {
        "quote_status": "ok",
        "product_id": product["product_id"],
        "name": product["name"],
        "description": product["description"],
        "category_id": product["category_id"],
        "category_name": product["category_name"],
        "stock_quantity": product["stock_quantity"],
        "specs": product["specs"],
        "available": product["available"],
        "availability_reason": product["availability_reason"],
        "payment_method": payment_method,
        "quantity": 1,
        "original_price_cents": product["price_cents"],
        "original_price_brl": product["price_brl"],
        "policy_source": POLICY_SOURCE,
        "data_source": "provided_snapshot",
    }
    if not product["available"]:
        result["quote_status"] = "unavailable"
        result["message"] = "Produto indisponivel para compra; buscar alternativas disponiveis."
        return result
    if len(promotions) > 1:
        result["quote_status"] = "needs_confirmation"
        result["promotions"] = promotions
        result["message"] = "Ha varias promocoes ativas; confirmar a campanha aplicavel com a equipe."
        return result
    promotion = promotions[0] if promotions else None
    pix_applied = promotion is None and payment_method == "pix"
    percent = promotion["discount_percent"] if promotion else 5 if pix_applied else 0
    final_cents = discounted_cents(product["price_cents"], percent)
    result.update({
        "discount_source": "promotion" if promotion else "pix" if pix_applied else "none",
        "discount_percent": percent,
        "discount_cents": product["price_cents"] - final_cents,
        "final_price_cents": final_cents,
        "final_price_brl": brl(final_cents),
        "pix_discount_applied": pix_applied,
        "promotion": promotion,
        "includes_shipping": False,
    })
    return result


def _active_promotions(connection):
    """Le todas as campanhas ativas de uma vez para evitar uma consulta por item."""
    grouped = {}
    for row in connection.execute(
        """SELECT product_id, promotion_id, discount_percent, description
           FROM promotions WHERE is_active = 1 ORDER BY promotion_id"""
    ):
        promotion = dict(row)
        product_id = promotion.pop("product_id")
        grouped.setdefault(product_id, []).append(promotion)
    return grouped


def _validate_payment(payment_method):
    if payment_method not in ("standard", "pix"):
        raise ValueError("payment_method deve ser standard ou pix")


def quote_product(product_id, payment_method="standard", database_path=DATABASE_PATH):
    """Cotacao de uma unidade, sem frete ou parcelamento.

    Varias promocoes ativas exigem confirmacao, sem escolher uma arbitrariamente.
    """
    _validate_payment(payment_method)
    if type(product_id) is not int or product_id <= 0:
        raise ValueError("product_id deve ser inteiro positivo")
    with closing(connect_catalog(database_path)) as connection:
        connection.execute("BEGIN")
        row = connection.execute(
            SELECT_PRODUCT + " WHERE p.product_id = ?", (product_id,)
        ).fetchone()
        if row is None:
            return {"quote_status": "not_found", "product_id": product_id}
        promotions = _active_promotions(connection)
        return _quote(serialize_product(row), promotions.get(product_id, []), payment_method)


def search_offers(query=None, category=None, max_price_cents=None,
                  payment_method="standard", limit=10, database_path=DATABASE_PATH):
    """Busca itens compraveis, aplicando o teto ao preco FINAL de uma unidade.

    Para esta base pequena, calcula o preco de todos os candidatos antes de
    filtrar, ordenar e limitar. standard considera promocoes; pix considera
    5% apenas quando nao ha promocao. Frete nao entra no teto informado.
    """
    _validate_payment(payment_method)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit deve ser inteiro entre 1 e 50")
    if max_price_cents is not None and (
        type(max_price_cents) is not int or max_price_cents < 0
    ):
        raise ValueError("max_price_cents deve ser inteiro nao negativo")
    if query is not None and not isinstance(query, str):
        raise ValueError("query deve ser texto")
    if category is not None and not isinstance(category, str):
        raise ValueError("category deve ser texto")
    tokens = normalize(query).split()
    category_term = normalize(category)
    category_term = CATEGORY_ALIASES.get(category_term, category_term)
    with closing(connect_catalog(database_path)) as connection:
        # As duas leituras compartilham a mesma visao do banco.
        connection.execute("BEGIN")
        rows = connection.execute(
            SELECT_PRODUCT + " WHERE p.status = 'active' AND p.stock_quantity > 0"
        ).fetchall()
        promotions = _active_promotions(connection)
    matches, unresolved = [], []
    for row in rows:
        product = serialize_product(row)
        text = normalize(product["name"] + " " + (product["description"] or ""))
        if not all(token in text for token in tokens):
            continue
        if category_term and category_term not in normalize(product["category_name"]):
            continue
        quote = _quote(product, promotions.get(product["product_id"], []), payment_method)
        if quote["quote_status"] != "ok":
            unresolved.append(quote)
            continue
        if max_price_cents is None or quote["final_price_cents"] <= max_price_cents:
            matches.append(quote)
    matches.sort(key=lambda item: (item["final_price_cents"], item["product_id"]))
    return {
        "items": matches[:limit],
        "total_matches": len(matches),
        "has_more": len(matches) > limit,
        "payment_method": payment_method,
        "price_basis": "final_price",
        "includes_shipping": False,
        "needs_confirmation": unresolved,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, help="ID do produto")
    parser.add_argument("--payment", choices=("standard", "pix"), default="standard")
    parser.add_argument("--query", help="Palavras do nome ou descricao")
    parser.add_argument("--category", help="Categoria; por exemplo, ukulele")
    parser.add_argument("--max-price", help="Preco final maximo em reais, sem frete")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    try:
        if args.id is not None:
            if args.query or args.category or args.max_price is not None or args.limit != 10:
                raise ValueError("Use --id sem filtros de busca; --payment e permitido")
            result = quote_product(args.id, args.payment)
        else:
            maximum = parse_brl(args.max_price) if args.max_price is not None else None
            result = search_offers(
                query=args.query, category=args.category, max_price_cents=maximum,
                payment_method=args.payment, limit=args.limit,
            )
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Falha na cotacao: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
