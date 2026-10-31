"""Cotacao de uma unidade: promocao ativa OU 5% no PIX, sem acumular.

Execute na raiz: python app/pricing.py --id 127 --payment pix
O preco final e arredondado para centavos, com meio centavo para cima.
A vigencia segue is_active na base fornecida, sem inferir datas pela descricao.
"""

import argparse
import json
import sqlite3
from contextlib import closing

if __package__:
    from .catalog import DATABASE_PATH, connect_catalog, get_product
else:
    from catalog import DATABASE_PATH, connect_catalog, get_product


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


def quote_product(product_id, payment_method="standard", database_path=DATABASE_PATH):
    """Calcula preco para uma unidade disponivel, sem frete ou parcelamento.

    standard usa preco de tabela ou promocao; pix aplica 5% apenas na ausencia
    de promocao ativa. Havendo varias promocoes ativas, pede confirmacao da
    equipe em vez de escolher ou acumular campanhas sem regra definida.
    """
    if payment_method not in ("standard", "pix"):
        raise ValueError("payment_method deve ser standard ou pix")
    product = get_product(product_id, database_path)
    if product is None:
        return {"quote_status": "not_found", "product_id": product_id}
    result = {
        "quote_status": "ok",
        "product_id": product_id,
        "name": product["name"],
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
    with closing(connect_catalog(database_path)) as connection:
        rows = connection.execute(
            """SELECT promotion_id, discount_percent, description
               FROM promotions WHERE product_id = ? AND is_active = 1
               ORDER BY promotion_id""",
            (product_id,),
        ).fetchall()
    promotions = [dict(row) for row in rows]
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, required=True, help="ID do produto")
    parser.add_argument("--payment", choices=("standard", "pix"), default="standard")
    args = parser.parse_args()
    try:
        result = quote_product(args.id, args.payment)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Falha na cotacao: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
