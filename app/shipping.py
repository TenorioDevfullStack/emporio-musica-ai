"""Estimativa de frete baseada nas secoes 5.1 e 5.2 do manual.

Coloque em app/shipping.py. Nao usa API nem requer novas dependencias.
Exemplo: python app/shipping.py --region metro_campo_grande --order-total 600
O total informado e o valor do pedido sem frete, em reais na CLI.
O manual nao define se o limiar usa valor antes/depois dos descontos; este
modulo nao escolhe essa base nem calcula o total do carrinho automaticamente.
"""

import argparse
import json

if __package__:
    from .catalog import parse_brl
else:
    from catalog import parse_brl


REGIONS = ("metro_campo_grande", "other_city", "unknown")
THRESHOLD_CENTS = 50000
LOCAL_FEE_CENTS = 3500


def quote_shipping(order_total_cents=None, region="unknown", large_instrument=None):
    """Estimativa de entrega; nunca cotacao real de transportadora.

region representa uma classificacao informada, nao geolocalizacao de CEP.
order_total_cents deve vir do valor do pedido informado pelo usuario, sem
frete. Nao assumir se descontos entram no limiar sem confirmar a regra.
"""
    if not isinstance(region, str) or region not in REGIONS:
        raise ValueError("region deve ser metro_campo_grande, other_city ou unknown")
    if order_total_cents is not None and (
            type(order_total_cents) is not int or order_total_cents <= 0):
        raise ValueError("order_total_cents deve ser inteiro positivo em centavos")
    if large_instrument is not None and type(large_instrument) is not bool:
        raise ValueError("large_instrument deve ser booleano ou None")
    result = {
        "status": "needs_information",
        "region": region,
        "region_source": "provided_classification",
        "order_total_cents": order_total_cents,
        "order_total_brl": money(order_total_cents) if order_total_cents is not None else None,
        "amount_basis": "provided_order_total_excluding_shipping",
        "shipping_cents": None,
        "shipping_brl": None,
        "grand_total_cents": None,
        "grand_total_brl": None,
        "delivery_business_days": None,
        "large_instrument": large_instrument,
        "is_estimate": True,
        "carrier_api_called": False,
        "policy_source": {"document": "políticas_da_loja.pdf",
                          "sections": ["5.1", "5.2"], "pages": [4, 5]},
        "assumptions": [
            "O valor informado representa o pedido sem frete.",
            "O manual nao especifica se o limiar de gratuidade considera o valor antes ou depois dos descontos."
        ],
    }
    if region == "unknown":
        result.update({"reason": "destination_region_required",
                       "message": "Informe se a entrega e na regiao metropolitana de Campo Grande/MS ou em outra cidade. O sistema nao classifica CEPs automaticamente."})
        return result
    if region == "other_city":
        result.update({
            "status": "requires_quote", "reason": "external_shipping_not_integrated",
            "policy_source": {"document": "políticas_da_loja.pdf", "sections": ["5.2"], "pages": [4, 5]},
            "shipping_options": [
                {"carrier": "Correios", "service": "PAC", "estimated_business_days": {"min": 5, "max": 12}},
                {"carrier": "Correios", "service": "SEDEX", "estimated_business_days": {"min": 2, "max": 5}},
                {"carrier": "Jadlog", "service": ".package", "estimated_business_days": {"min": 3, "max": 8}},
            ],
            "required_for_quote": ["destination_postal_code", "weight", "dimensions"],
            "tracking_included": True, "insurance_included": True,
            "message": "Para outras cidades, o preco depende de CEP, peso e dimensoes. Consulte a equipe para uma cotacao; os prazos do manual sao estimativas e nao datas garantidas.",
        })
        if large_instrument is not False:
            result["special_shipping_note"] = "Instrumentos de grande porte podem exigir frete especial com cotacao individual."
        return result
    result["policy_source"] = {"document": "políticas_da_loja.pdf", "sections": ["5.1"], "pages": [4]}
    result["delivery_business_days"] = {"min": 1, "max": 3}
    if order_total_cents is None:
        result.update({"reason": "order_total_required",
                       "message": "Informe o valor do pedido sem frete. Se houver desconto, confirme qual valor a loja usa para o limiar de gratuidade."})
        return result
    if order_total_cents == THRESHOLD_CENTS:
        result.update({"status": "needs_confirmation", "reason": "shipping_exactly_500",
                       "message": "O manual define frete para pedidos abaixo e acima de R$ 500,00, mas nao para exatamente R$ 500,00. Confirme a taxa com a equipe."})
        return result
    fee = 0 if order_total_cents > THRESHOLD_CENTS else LOCAL_FEE_CENTS
    total = order_total_cents + fee
    result.update({"status": "ok", "reason": "local_free_shipping" if fee == 0 else "local_fixed_fee",
                   "shipping_cents": fee, "shipping_brl": money(fee),
                   "grand_total_cents": total, "grand_total_brl": money(total),
                   "message": "Estimativa pela regra local do manual, com prazo de 1 a 3 dias uteis. Confirme com a equipe quando a base do valor do pedido depender de descontos."})
    return result


def money(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=REGIONS, default="unknown")
    parser.add_argument("--order-total", help="Valor informado do pedido sem frete, ex.: 600 ou 499.99")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--large-instrument", dest="large_instrument", action="store_true")
    group.add_argument("--regular-size", dest="large_instrument", action="store_false")
    parser.set_defaults(large_instrument=None)
    args = parser.parse_args()
    try:
        amount = parse_brl(args.order_total) if args.order_total is not None else None
        result = quote_shipping(amount, args.region, args.large_instrument)
    except ValueError as exc:
        parser.exit(1, f"Falha na estimativa: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
