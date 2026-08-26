# Hugging Face ile Veri Seti Hazırlama, Model Distilasyonu ve Hesaplama Gücü Rehberi

Bu rehber; Hugging Face ekosisteminde veri seti hazırlama, model distilasyonu (TRL), ücretsiz ve ücretli donanım/hesaplama kaynakları (ZeroGPU, Spaces, Jobs, Colab, Kaggle) ile optimizasyon tekniklerini tek bir çatı altında toplar.

---

## 1. Veri Seti Hazırlama ve Ön İşleme

Hugging Face `datasets` kütüphanesi CPU/RAM optimizasyonları sunar:

* **Batch İşleme:** `dataset.map(tokenize_fn, batched=True, batch_size=1000)`
* **Multiprocessing (Çoklu Çekirdek):** `dataset.map(process_fn, num_proc=8)`
* **Streaming Modu (Bellek Tasarrufu):** `load_dataset("dataset_name", streaming=True)` (Büyük veri setlerini diske/RAM'e indirmeden akış halinde işler)
* **Sentetik Veri / Ağır İşlemler:** HF Jobs üzerinden GPU (`flavor="a10g-large"` vb.) kiralayarak arka planda betik çalıştırılabilir.

---

## 2. Model Distilasyonu (Knowledge Distillation)

TRL kütüphanesinin `DistillationTrainer` sınıfı, büyük bir Teacher modelden küçük bir Student modele bilgi aktarmayı kolaylaştırır.

### Temel Pipeline ve vLLM Hızlandırması
* **LoRA / PEFT:** Öğrenci modelde bellek tasarrufu için LoRA (`LoraConfig`) kullanılabilir.
* **vLLM Entegrasyonu (40x Hız):** `use_vllm=True`, `vllm_mode="colocate"`, `vllm_gpu_memory_utilization=0.3` parametreleri ile çıkarım hızı katlanır.
* **Harici Teacher Sunucusu:** Teacher modeli çok büyükse (>100B) `use_teacher_server=True` ve `teacher_model_server_url="http://localhost:8000"` ile harici vLLM sunucusuna yönlendirilebilir.

```python
from datasets import load_dataset
from trl import DistillationTrainer, DistillationConfig
from peft import LoraConfig

dataset = load_dataset("trl-lib/ultrafeedback-prompt")

peft_config = LoraConfig(
    r=64,
    lora_alpha=16,
    target_modules=["q_proj", "v_proj"],
)

training_args = DistillationConfig(
    output_dir="distilled-model",
    num_train_epochs=1,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=8,
    learning_rate=2e-5,
    bf16=True,
    lmbda=1.0,  # On-policy
    beta=1.0,   # Reverse KL divergence
    temperature=1.0,
    max_completion_length=512,
    use_vllm=True,
    vllm_gpu_memory_utilization=0.3,
    teacher_model_name_or_path="Qwen/Qwen2.5-7B-Instruct",
)

trainer = DistillationTrainer(
    model="Qwen/Qwen2.5-0.5B-Instruct",       # Student
    teacher_model="Qwen/Qwen2.5-7B-Instruct", # Teacher
    args=training_args,
    train_dataset=dataset["train"],
    peft_config=peft_config,
)

trainer.train()
```

---

## 3. Ücretsiz ve Ücretli Hesaplama Gücü Karşılaştırması

### Ücretsiz Kaynaklar

| Kaynak | Donanım / Limit | Maliyet | En İyi Kullanım Alanı |
|---|---|---|---|
| **HF ZeroGPU** | RTX Pro 6000 (48GB - 96GB VRAM) / Günlük 5 dk (PRO: 40 dk) | Ücretsiz | Hızlı Gradio demoları, inference, mini distilasyon adımları |
| **HF CPU Basic Space** | 2 vCPU, 16 GB RAM, 50 GB disk | Ücretsiz | Veri ön işleme, CPU tabanlı web arayüzleri |
| **HF Inference API (Serverless)** | ~10B parametreye kadar modeller, $0.10/ay kredi | Ücretsiz | API prototipleme ve test |
| **AutoTrain Advanced (Lokal)** | Kendi CPU/GPU donanımınız | Ücretsiz | Tam yerel kontrol ile SFT, DPO/ORPO eğitimi |
| **Google Colab** | 1x NVIDIA T4 (12GB VRAM), ~12 saatlik oturum | Ücretsiz | Prototip notebook eğitimi, veri hazırlığı |
| **Kaggle** | 2x NVIDIA T4 (24GB VRAM), haftalık 30 saat | Ücretsiz | Orta ölçekli model eğitimi, LoRA fine-tuning |

### Ücretli Donanım Seçenekleri (HF Jobs / Spaces)

| Model Boyutu | Önerilen Donanım | Yaklaşık Maliyet/Saat |
|---|---|---|
| **< 1B** | `t4-small` | ~$0.50 - $1.00 |
| **1 - 3B** | `a10g-small` | ~$1.00 - $2.00 |
| **3 - 7B** | `l4x1` / `a10g-large` | ~$2.00 - $4.00 |
| **7 - 13B** | `a10g-large` (LoRA ile) veya `a100-large` | ~$4.00 - $12.00 |
| **> 13B** | `a100-large` / `h200` multi-GPU (LoRA/QLoRA) | ~$8.00 - $12.00+ |

---

## 4. ZeroGPU Kullanım Detayları (Gradio Spaces)

Spaces üzerinde `@spaces.GPU` dekoratörüyle fonksiyon seviyesinde GPU ayrılabilir:

```python
import spaces

@spaces.GPU  # 48GB VRAM (large - varsayılan kota tüketimi)
def generate(prompt):
    return model(prompt)

@spaces.GPU(size="xlarge", duration=120)  # 96GB VRAM (2x kota tüketimi), maks 120 sn
def large_generate(prompt):
    return large_model(prompt)
```
*Ücretsiz hesaplar en fazla 2 ZeroGPU Space barındırabilir (hesabın 30 günden eski ve e-posta onaylı olması gerekir).*

---

## 5. Uçtan Uca Maliyetsiz / Düşük Maliyetli İş Akışı Önerisi

1. **Veri Hazırlığı (Tamamen Ücretsiz):** `datasets` ile CPU üzerinde streaming ve multiprocessing (`num_proc=4-8`) kullanarak veriyi tokenize edin ve temizleyin.
2. **Prototip Testi (ZeroGPU / Colab):** Küçük veri parçasıyla eğitim betiğini ve parametreleri test edin (`max_steps=50-100`).
3. **Tam Eğitim (Kaggle / Colab veya HF Jobs):**
   * **Ücretsiz yol:** Kaggle (haftalık 30 saat 2x T4 GPU) üzerinde LoRA + TRL DistillationTrainer ile eğitimi tamamlayın.
   * **Ölçekli / Ücretli yol:** Modeller 7B+ olduğunda veya süre kısıtı kalktığında HF Jobs (`a10g-large` / `a100-large`) kullanarak arka planda çalıştırın.
