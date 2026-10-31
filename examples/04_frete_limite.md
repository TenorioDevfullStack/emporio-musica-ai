# 04 - Valor exatamente no limite sem regra definida

Registro real fornecido pelo autor em 31/10/2026 durante a validação da integração de frete. Resposta transcrita do JSON; metadados selecionados.

**Cliente:** Meu pedido totaliza 500 reais sem frete, para entrega na região metropolitana de Campo Grande/MS. Quanto fica o frete?

**Agente:**

O manual define frete para pedidos abaixo e acima de R$ 500,00, mas nao para exatamente R$ 500,00. Confirme a taxa com a equipe. Fonte: políticas_da_loja.pdf, seção(ões) 5.1, página(s) 4.

**Metadados observados:** `status: needs_confirmation`; ferramenta `quote_shipping`; `response_origin: shipping_guard`; 1 chamada; 1.218 tokens. `shipping_cents: null`; `grand_total_cents: null`; motivo `shipping_exactly_500`.

**O que demonstra:** o agente não transforma ausência de regra em gratuidade nem aplica R$ 35 arbitrariamente. O código de saída 2 representa o encaminhamento esperado desse caso, não uma falha de conexão.
