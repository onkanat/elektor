# Elektor Dataset Quality Analysis & Optimization Report

We have analyzed the datasets compiled from the 10-article pipeline run (`sft_dataset.jsonl`, `dpo_dataset.jsonl`, `chat_dataset.jsonl`, and `tr_sft_dataset.jsonl`). 

Overall, the data quality is **exceptionally high**, showing deep technical reasoning and precise translations. Below is a structured analysis of the dataset quality and proposed optimization recommendations.

---

## 🔍 Dataset Quality Analysis

### 1. English SFT Dataset (`sft_dataset.jsonl`)
- **Strengths**:
  - **Technical Precision**: Rather than asking generic summary questions, the questions target specific mathematical formulas (e.g. pulse-rate calculation $p = \frac{n \cdot n_{cyl}}{60 \cdot a}$), logic IC pins (MM5314 pins 11, 13, 14, 15), and operational characteristics.
  - **Context-Aware Inputs**: The `input` field is formatted correctly with `Context: Elektor Magazine (1974) article '...'`, enabling models trained on this data to learn document-grounded question answering.
- **Weaknesses**:
  - **OCR Noise**: Typographical noise from OCR is present in some title metadata (e.g., `sw1ng1ng inductor` instead of `swinging inductor` due to 'i' and '1' character recognition errors).

### 2. English DPO Dataset (`dpo_dataset.jsonl`)
- **Strengths**:
  - **Realistic Engineering Trade-Offs**: The `chosen` vs `rejected` pairs reflect actual engineering decisions. The rejected answers contain logical errors that sound plausible but are technically incorrect (e.g., suggesting parallel display driving for a multiplexed MM5314 IC, or claiming complementary output stages use identical NPN transistors).
- **Weaknesses**:
  - **Missing Context**: Currently, the DPO dataset only contains `prompt`, `chosen`, and `rejected`. It lacks the `input` (context) field, which is critical for context-constrained preference tuning.

### 3. Turkish SFT Dataset (`tr_sft_dataset.jsonl`)
- **Strengths**:
  - **Translation Fidelity**: Google's `translategemma:12b` model translates technical explanations beautifully while keeping critical engineering terms (op-amp, CMOS, Schmitt trigger, RPM, DIN) intact in Turkish context.
- **Weaknesses**:
  - **Monotonous Prompt Structure**: The prompts always use the template: *"Elektor dergisinde {year} yılında yayınlanan '{title}' makalesi ne hakkındadır? Kısaca özetler misiniz?"*. This can be diversified to prevent overfitting.

---

## 🛠️ Optimization Recommendations

Based on these findings, we recommend the following code modifications before running the full 11,000+ article production run:

### 1. OCR Pre-Processing & Cleanup
Add a basic string sanitizer in `pipeline/extractor.py` to fix common OCR artifacts in titles and text before inserting them into SQLite.
```python
def sanitize_ocr_text(text):
    # Common OCR replacements
    replacements = {
        "sw1ng1ng": "swinging",
        "ditltal": "digital",
        "COllwmeasured": "measured"
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text
```

### 2. Math & LaTeX Formatting in Prompts
Instruct the analyzer LLM to format mathematical equations in LaTeX notation (e.g., `\(p = \frac{n \cdot n_{cyl}}{60 \cdot a}\)`). This helps downstream models learn beautiful rendering and standard formatting.

### 3. Align DPO Context Structure
Modify `pipeline/dataset_builder.py` to include the `input` context field in the exported DPO dataset:
```diff
 dpo_records.append({
     "prompt": q,
+    "input": f"Context: Elektor Magazine ({year}) article '{title}'",
     "chosen": chosen,
     "rejected": rej
 })
```

### 4. Diversified Turkish Prompts
Introduce multiple prompt templates in `pipeline/dataset_builder.py` to make the Turkish SFT dataset more robust:
```python
import random

templates = [
    "Elektor dergisinde {year} yılında yayınlanan '{title}' makalesi ne hakkındadır? Kısaca özetler misiniz?",
    "Lütfen {year} yılına ait '{title}' başlıklı Elektor makalesinin özetini Türkçe olarak yazın.",
    "Elektor dergisindeki '{title}' ({year}) çalışmasının ana konusunu ve teknik içeriğini özetleyebilir misiniz?"
]
prompt = random.choice(templates).format(year=year, title=tr_title)
```
