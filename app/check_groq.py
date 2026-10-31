"""Teste pequeno de acesso a Groq, sem exibir a chave ou repetir chamadas.

Execute na raiz: python app/check_groq.py
Le GROQ_API_KEY e, opcionalmente, GROQ_MODEL do ambiente ou do .env da raiz.
Variaveis ja definidas no terminal tem prioridade sobre o arquivo .env.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    Groq,
    RateLimitError,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "openai/gpt-oss-120b"


def check_connection():
    load_dotenv(PROJECT_DIR / ".env", override=False)
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    model = (os.getenv("GROQ_MODEL") or DEFAULT_MODEL).strip()
    if not key or key == "SUA_CHAVE_AQUI":
        raise ValueError("Configure GROQ_API_KEY no arquivo .env da raiz do projeto")
    # Uma tentativa, timeout curto e resposta pequena para validar o acesso.
    with Groq(api_key=key, timeout=30.0, max_retries=0) as client:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Responda de forma breve, em portugues."},
                {"role": "user", "content": "Responda apenas: Conexao OK."},
            ],
            reasoning_effort="low",
            temperature=0,
            max_completion_tokens=256,
        )
    if not response.choices:
        raise ValueError("A API retornou uma resposta sem alternativas")
    choice = response.choices[0]
    content = (choice.message.content or "").strip()
    usage = response.usage
    result = {
        "status": "ok",
        "provider": "groq",
        "model": model,
        "response": content,
        "finish_reason": choice.finish_reason,
        "usage": {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        } if usage else None,
    }
    if not content or choice.finish_reason == "length":
        result["status"] = "incomplete_response"
        result["message"] = "A API respondeu, mas a geracao nao terminou com uma resposta textual completa."
    return result


def main():
    try:
        result = check_connection()
    except AuthenticationError:
        message = "Autenticacao recusada. Confira a chave da Groq salva no .env, sem envia-la pelo chat."
    except RateLimitError:
        message = "Limite de uso atingido. Aguarde a renovacao da cota e tente novamente; o teste nao faz repeticoes automaticas."
    except APITimeoutError:
        message = "A Groq nao respondeu no prazo de 30 segundos. Tente novamente mais tarde."
    except APIConnectionError:
        message = "Nao foi possivel conectar a Groq. Confira a conexao de rede."
    except APIStatusError as exc:
        # Nao imprimir o corpo bruto de erros, que pode conter dados sensiveis.
        if exc.status_code == 404:
            message = "Modelo nao encontrado ou indisponivel para esta conta."
        elif exc.status_code == 403:
            message = "Acesso recusado. Confira as permissoes do modelo na sua conta Groq."
        else:
            message = f"A Groq retornou HTTP {exc.status_code}. A integracao ainda precisa ser validada."
    except (OSError, ValueError) as exc:
        message = str(exc)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ok" else 2
    print(f"Falha no teste: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
