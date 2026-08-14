"""
V2 UPGRADE PATH — not needed for the MVP.

Once real client queries have been logged through /extract-specs during
UAT (Week 8) or a soft-launch pilot, and staff have corrected the rule-based
extractor's mistakes, you'll have annotated training data. This script is
where a real spaCy NER pipeline gets trained on it.

Steps to actually use this:
  1. Export logged (query, corrected_entities) pairs from the `quotes` table.
  2. Convert them to spaCy's training format (offsets into the raw text for
     each entity span — item_type, quantity, paper_size, etc.)
  3. Fine-tune `en_core_web_sm` (or blank model) with a custom NER pipe.
  4. Evaluate against a held-out set; only ship it if it beats the
     rule-based extractor's accuracy on the same set.
  5. Swap it in behind app/services/nlp_extractor.py's `extract()` function
     — keep the same input/output signature so the router is untouched.

Do NOT attempt this in Week 3 as originally scoped unless you already have
50-100+ real annotated examples by then. Rule-based extraction is the
correct Week 3 deliverable; this file is Week 8+ or post-internship work.
"""

import spacy
from spacy.training import Example


def load_training_data(path: str) -> list[tuple[str, dict]]:
    """
    Expected format (JSONL), one example per line:
    {"text": "500 copies of A4 glossy flyers", "entities": [[0,3,"QUANTITY"],[13,15,"PAPER_SIZE"],[16,22,"FINISH"],[23,29,"ITEM_TYPE"]]}
    """
    import json
    examples = []
    with open(path) as f:
        for line in f:
            row = json.loads(line)
            examples.append((row["text"], {"entities": row["entities"]}))
    return examples


def train(data_path: str, output_dir: str, n_iter: int = 30):
    nlp = spacy.blank("en")
    ner = nlp.add_pipe("ner")

    for label in ["ITEM_TYPE", "QUANTITY", "PAPER_SIZE", "FINISH", "PRINT_SIDE", "COLOR_MODE"]:
        ner.add_label(label)

    train_data = load_training_data(data_path)

    nlp.begin_training()
    for i in range(n_iter):
        losses = {}
        for text, annotations in train_data:
            doc = nlp.make_doc(text)
            example = Example.from_dict(doc, annotations)
            nlp.update([example], losses=losses)
        print(f"Iteration {i+1}/{n_iter} — losses: {losses}")

    nlp.to_disk(output_dir)
    print(f"Model saved to {output_dir}")


if __name__ == "__main__":
    # train("data/annotated_queries.jsonl", "models/print_ner_v1")
    print(__doc__)
