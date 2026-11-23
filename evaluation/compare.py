"""Execute com python -m evaluation.compare --model-dir CAMINHO."""
import argparse
import csv
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import onnxruntime as ort
import pgserver
from psycopg import sql
from tokenizers import Tokenizer

from app.policies import load_sections, rank_sections, tokens

HERE = Path(__file__).resolve().parent


class Encoder:
    def __init__(self, model_dir):
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.no_padding()
        self.tokenizer.enable_truncation(max_length=128, stride=0)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        self.model = ort.InferenceSession(str(model_dir / "model.onnx"), options,
                                          providers=["CPUExecutionProvider"])
        self.inputs = [item.name for item in self.model.get_inputs()]

    def vector(self, text):
        encoding = self.tokenizer.encode(text)
        total = np.zeros(384, dtype=np.float64)
        for window in [encoding, *encoding.overflowing]:
            arrays = {"input_ids": window.ids, "attention_mask": window.attention_mask,
                      "token_type_ids": window.type_ids}
            inputs = {key: np.asarray([arrays[key]], dtype=np.int64) for key in self.inputs}
            hidden = self.model.run(["last_hidden_state"], inputs)[0][0]
            total += hidden.sum(axis=0)  # sem padding, média ponderada por token antes da normalização
        return json.dumps((total / np.linalg.norm(total)).tolist())


def vector_search(encoder, sections, questions, temp):
    # Uma instância PostgreSQL local em modo single-user dispensa rede e credenciais.
    db = temp / "db"
    output = temp / "neighbors.csv"
    pgserver.initdb(["--no-sync", "--encoding=UTF8", "--locale=C"], pgdata=db)
    commands = [
        "BEGIN",
        "CREATE EXTENSION vector",
        "CREATE TABLE passages (id text PRIMARY KEY, embedding vector(384))",
        "CREATE TABLE queries (n integer PRIMARY KEY, embedding vector(384))",
    ]
    for section in sections:
        vector = encoder.vector(section["title"] + "\n" + section["text"])
        commands.append(sql.SQL("INSERT INTO passages VALUES ({}, {}::vector)").format(
            section["section_id"], vector).as_string())
    for index, item in enumerate(questions):
        commands.append(sql.SQL("INSERT INTO queries VALUES ({}, {}::vector)").format(
            index, encoder.vector(item["question"])).as_string())
    commands.append(sql.SQL("COPY (SELECT n, ARRAY(SELECT id FROM passages "
                            "ORDER BY embedding <=> queries.embedding, id LIMIT 3) "
                            "FROM queries ORDER BY n) TO {} WITH (FORMAT CSV)").format(str(output)).as_string())
    commands.append("COMMIT")
    binary = Path(pgserver.__file__).parent / "pginstall" / "bin" / "postgres"
    proc = subprocess.run([binary, "--single", "-D", db, "postgres"],
                          input=";\n".join(commands) + ";\n", text=True, capture_output=True, check=True)
    if "ERROR:" in proc.stderr or not output.exists():
        raise RuntimeError(proc.stderr)
    with output.open(encoding="utf-8") as handle:
        return [ids.strip("{}").split(",") for _, ids in csv.reader(handle)]


def compare(encoder, sections, questions, temp):
    neighbors = vector_search(encoder, sections, questions, temp)
    results = []
    known_ids = {section["section_id"] for section in sections}
    for item, vector_ids in zip(questions, neighbors, strict=True):
        question, expected = item["question"], item["section_id"]
        if expected not in known_ids:
            raise ValueError(f"Seção desconhecida: {expected}")
        ranked = rank_sections(sections, tokens(question))
        bm25 = [sections[i]["section_id"] for _, i in ranked[:3]]
        results.append({"question": question, "expected": expected, "bm25": bm25,
                        "pgvector": vector_ids})
    hits = {method: sum(r["expected"] in r[method] for r in results)
            for method in ("bm25", "pgvector")}
    return {"sections": len(sections), "questions": len(results), "hits_at_3": hits, "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    args = parser.parse_args()
    encoder = Encoder(args.model_dir)
    sections, _ = load_sections()
    with (HERE / "questions.tsv").open(encoding="utf-8") as handle:
        questions = list(csv.DictReader(handle, delimiter="\t"))
    with TemporaryDirectory() as temp:
        report = compare(encoder, sections, questions, Path(temp))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
