# 03 - Frete local com valor informado pelo cliente

Registro real fornecido pelo autor em 31/10/2026, após a correção da resposta de frete. Resposta transcrita do JSON; metadados selecionados.

**Cliente:** Meu pedido totaliza 600 reais sem frete, para entrega na região metropolitana de Campo Grande/MS. Quanto fica o frete?

**Agente:**

Para entrega na região metropolitana de Campo Grande/MS, considerando o valor informado do pedido de R$ 600,00 sem frete, o frete estimado é gratuito (R$ 0,00). O total com frete é R$ 600,00. Prazo estimado: 1 a 3 dias úteis. O manual não especifica se o limiar de gratuidade considera o valor antes ou depois dos descontos. Se houver dúvida sobre essa base, confirme com a equipe antes de considerar a estimativa definitiva. Fonte: políticas_da_loja.pdf, seção(ões) 5.1, página(s) 4.

**Metadados observados:** `status: ok`; ferramenta `quote_shipping`; `response_origin: shipping_guard`; 1 chamada; 1.220 tokens. `shipping_cents: 0`; `grand_total_cents: 60000`; `carrier_api_called: false`.

**O que demonstra:** cálculo em código e resposta controlada preservando uma indefinição do manual. Não houve consulta a transportadora nem promessa de data exata.
