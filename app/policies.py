"""Busca textual por secoes no PDF original, com referencias de pagina.

Dependencia: pypdf==6.21.4
Execute: python app/policies.py --query "posso devolver uma compra online?"
O resultado fornece contexto documental. Nao aprova devolucoes nem resolve
automaticamente contradicoes. A busca usa BM25 e sinonimos simples em portugues.
"""

import argparse
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

from pypdf import PdfReader


POLICY_PATH = Path(__file__).resolve().parents[1] / "data" / "políticas_da_loja.pdf"
STOPWORDS = set("a ao aos as ate com como da das de do dos e em eu me meu minha na nas no nos o os ou para pela pelo por posso qual quais que quero se seu sua tem um uma voce loja emporio musica".split())
ALIASES = {
    "internet": "online", "site": "online",
    "telefone": "contato", "whatsapp": "contato", "email": "contato",
    "abre": "horario", "aberto": "horario", "abrem": "horario",
    "fechado": "horario", "funcionamento": "horario",
    "pagar": "pagamento", "paguei": "pagamento", "cartoes": "cartao",
}
PREFIXES = {
    "arrepend": "arrependimento", "devol": "devolucao", "reembols": "reembolso",
    "troc": "troca", "garant": "garantia", "defeit": "defeito",
    "parcel": "parcelamento", "promoc": "promocao", "descont": "desconto",
    "entreg": "entrega", "rastre": "rastreamento", "compr": "compra",
    "pagament": "pagamento", "acessor": "acessorio",
}
TOPIC_TOKENS = {
    "arrependimento", "devolucao", "reembolso", "troca", "garantia", "defeito",
    "parcelamento", "promocao", "desconto", "entrega", "rastreamento",
    "pagamento", "acessorio", "frete", "pix", "contato", "endereco", "horario",
    "privacidade", "reclamacao", "estoque",
}


def normalize(text):
    return "".join(
        char for char in unicodedata.normalize("NFKD", text).casefold()
        if not unicodedata.combining(char)
    )


def tokens(text):
    words = re.findall(r"[a-z0-9]+", normalize(text).replace("e-mail", "email"))
    result = []
    for word in words:
        if word in STOPWORDS or len(word) < 2:
            continue
        word = ALIASES.get(word, word)
        for prefix, canonical in PREFIXES.items():
            if word.startswith(prefix):
                word = canonical
                break
        result.append(word)
    return result


def load_sections(pdf_path=POLICY_PATH):
    """Extrai titulos e conteudo; secoes podem continuar em varias paginas."""
    path = Path(pdf_path)
    sections = []
    current = {"section_id": "cover", "title": "Capa do manual", "pages": [], "lines": []}
    seen = {"cover"}
    heading_pattern = re.compile(r"^(\d+(?:\.\d+)?)(?:\.)?\s+(.+)$")
    with path.open("rb") as handle:
        reader = PdfReader(handle)
        page_count = len(reader.pages)
        for page_number, page in enumerate(reader.pages, 1):
            text = page.extract_text(extraction_mode="layout") or ""
            if not text.strip():
                raise ValueError(f"Pagina {page_number} sem texto extraivel; revisar o PDF")
            for raw_line in text.splitlines():
                line = re.sub(r"\s+", " ", raw_line.strip())
                if not line:
                    continue
                cleaned = normalize(line)
                if (cleaned == "emporio da musica manual de politicas e procedimentos"
                        or re.fullmatch(r"pagina \d+", cleaned)):
                    continue
                heading = heading_pattern.match(line)
                # Os passos '1. Saudacao:' nao sao titulos de secao.
                if heading and ":" not in heading[2] and heading[1] not in seen:
                    sections.append(current)
                    section_id, title = heading.groups()
                    current = {"section_id": section_id, "title": title,
                               "pages": [], "lines": []}
                    seen.add(section_id)
                else:
                    current["lines"].append(line)
                if page_number not in current["pages"]:
                    current["pages"].append(page_number)
    sections.append(current)
    for section in sections:
        section["text"] = "\n".join(section.pop("lines"))
    if len(sections) <= 1:
        raise ValueError("Nao foi possivel identificar as secoes do manual")
    return sections, page_count


def rank_sections(sections, query_tokens):
    """BM25, com reforco para termos encontrados no titulo. Score nao e confianca."""
    documents = [Counter(tokens(s["title"] + " " + s["text"])) for s in sections]
    lengths = [sum(doc.values()) for doc in documents]
    average = sum(lengths) / len(documents) or 1
    ranked = []
    terms = set(query_tokens)
    for index, counts in enumerate(documents):
        matched = {term for term in terms if counts[term]}
        # Evita recuperar secoes por uma palavra generica isolada (ex.: 'tempo').
        # Isto e um filtro lexical, nao um classificador semantico de escopo.
        if not terms & TOPIC_TOKENS and len(matched) / max(len(terms), 1) < 0.5:
            continue
        score = 0.0
        title_tokens = set(tokens(sections[index]["title"]))
        for term in terms:
            frequency = counts[term]
            if not frequency:
                continue
            document_frequency = sum(term in doc for doc in documents)
            inverse_frequency = math.log(1 + (len(documents) - document_frequency + 0.5)
                                         / (document_frequency + 0.5))
            score += inverse_frequency * frequency * 2.5 / (
                frequency + 1.5 * (0.25 + 0.75 * lengths[index] / average)
            )
            if term in title_tokens:
                score += 2 * inverse_frequency
        if score > 0:
            ranked.append((score, index))
    return sorted(ranked, key=lambda pair: (-pair[0], pair[1]))


def related_context(query_tokens):
    """Curadoria explicita para nao separar condicoes e excecoes importantes."""
    terms = set(query_tokens)
    related, ambiguities = [], []
    if terms & {"devolucao", "arrependimento", "troca", "reembolso"}:
        related.append("4.4")
    if terms & {"devolucao", "arrependimento", "reembolso"}:
        related.append("4.1")
    if terms & {"pix", "pagamento", "promocao", "desconto"}:
        related.extend(["3", "6.2"])
    if "parcelamento" in terms:
        related.extend(["3", "3.1"])
        ambiguities.append({
            "code": "installment_conflict", "pages": [3], "sections": ["3", "3.1"],
            "note": "A tabela geral e as regras detalhadas diferem nas parcelas minimas. Confirmar a condicao aplicavel com a equipe.",
        })
    if "frete" in terms:
        related.extend(["5.1", "5.2"])
        ambiguities.append({
            "code": "shipping_exactly_500", "pages": [4], "sections": ["5.1"],
            "note": "O manual nao define o frete metropolitano para valor exatamente igual a R$ 500,00. Confirmar esse caso com a equipe.",
        })
    if terms & {"garantia", "defeito"}:
        related.extend(["4.2", "8.1", "8.2", "8.3"])
    if "contato" in terms:
        related.extend(["cover", "1.2", "7"])
        ambiguities.append({
            "code": "contact_conflict", "pages": [1, 2, 6], "sections": ["cover", "1.2", "7"],
            "note": "Ha telefones divergentes e variacao no e-mail entre partes do manual. Confirmar o contato correto com a equipe.",
        })
    return list(dict.fromkeys(related)), ambiguities


def search_policies(query, limit=3, pdf_path=POLICY_PATH):
    """Retorna trechos relevantes e contexto adicional, sem gerar uma resposta.

    limit controla correspondencias primarias. Secoes relacionadas sao adicionadas
    separadamente para preservar excecoes, condicoes e contradicoes conhecidas.
    As ambiguidades sao anotacoes revisadas, nao deteccao automatica generica.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query deve conter uma pergunta ou assunto")
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError("limit deve ser inteiro entre 1 e 5")
    sections, page_count = load_sections(pdf_path)
    query_tokens = tokens(query)
    ranked = rank_sections(sections, query_tokens)
    result = {
        "status": "context_found" if ranked else "not_found",
        "query": query,
        "document": Path(pdf_path).name,
        "page_count": page_count,
        "section_count": len(sections),
        "method": "bm25_sections_with_curated_context",
        "matches": [], "related_context": [], "ambiguities": [],
    }
    if not ranked:
        return result
    selected = set()
    for _, index in ranked[:limit]:
        result["matches"].append(dict(sections[index]))
        selected.add(sections[index]["section_id"])
    related, ambiguities = related_context(query_tokens)
    by_id = {section["section_id"]: section for section in sections}
    for section_id in related:
        if section_id in by_id and section_id not in selected:
            result["related_context"].append(dict(by_id[section_id]))
            selected.add(section_id)
    result["ambiguities"] = ambiguities
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    try:
        result = search_policies(args.query, args.limit)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Falha na busca de politicas: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
