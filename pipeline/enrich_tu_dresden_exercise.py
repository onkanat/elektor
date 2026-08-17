import os
import json
import sqlite3
from pathlib import Path
from pipeline.langextract_engine import LangExtractEngine

EXERCISE_SHEET_TEXT = """
Technische Universität Dresden
Vodafone Stiftungslehrstuhl Mobile Nachrichtensysteme
Prof. Dr.-Ing. Dr. h.c. G. Fettweis

Lab Work „Communications“ - Summer Semester 2026
Exercise Sheet 1: Signal Theory and LTI-Systems

Task 1: Signal Power (8 points)
Consider a voltage signal on a coaxial line with wave resistance R = 50 Ω according to Figure 1.
Amplitude A = 2 V, Period T = 40 ms, Frequency f = 25 Hz.

(a) Read the amplitude A in V and frequency f in Hz of the signal from Figure 1! (1 point)
(b) Provide a general formula for calculating the effective value of the power of any voltage signal V(t) over observation period T! (1 point)
(c) Calculate the power of the signal given in Figure 1! (1 point)
(d) How does the power of the signal change when the frequency is doubled? Explain why! (1 point)
(e) How does the power of the signal change when the amplitude is doubled? Explain why! (1 point)
(f) Provide a formula for converting power P, with respect to PREF = 1 mW, to power level L in dBm! Calculate the power level of the signal in Figure 1 in dBm! (1 point)
(g) Generate a signal with an amplitude of 2 V in the GNURadio simulation. Compare the power of the signal with its previously calculated value! (1 point)
(h) Investigate the flow graph of the simulation and briefly explain how the signal amplitude is calculated in the simulation! Hint: Consider the block "Signal Source"! (1 point)

Task 2: Amplifier and Channel (10 points)
Given is a transmitter/receiver system as in Figure 2 with transmit signal power PS = 250 mW, linear amplifier factor gTX = 16, channel loss LD, receiver LNA gain GRX1 = 10 dB and linear gain gRX2 = 75 (approx 80).

(a) Set the power of the transmit signal to PS = 250 mW in the simulation. Provide the power level of the signal LS in dBm! (1 point)
(b) The signal LS is now to be amplified with the linear factor gTX = 16. Provide the logarithmic gain gTX in dB! (1 point)
(c) Provide the value of the transmit signal PS,G in mW and LS,G in dBm! (1 point)
(d) Verify the simulated value PS,G with a calculation! (1 point)
(e) Set a distance d = 0.5 km and frequency f = 1000 MHz. How large is the channel attenuation LD in dB? (1 point)
(f) Enter the channel attenuation LD in dB into Table 1 using the simulation! (1 point)
(g) Describe analytically the relationship between channel attenuation and signal frequency! (1 point)
(h) Provide the receive power LR in dBm for the previously mentioned configuration! (1 point)
(i) Calculate the power of the output signal LR,G in dBm and PR,G in mW for LR = -10 dBm, logarithmic gain GRX1 = 10 dB and linear gain gRX2 = 75 (approx 80)! (1 point)
(j) Compare the calculated value for LR,G with the simulated value! (1 point)

Task 3: Signal-to-Noise Ratio (17 points)
(a) Provide a general formula for the signal-to-noise ratio (SNR)! (1 point)
(b) In the simulation, a value for the SNR of the input signal SNRIN is given. The input signal is noise-free. Explain whether the SNR is a meaningful metric under this condition! (1 point)
(c) Assume that LS = 0 dBm, logarithmic gain GTX = 13 dB, and noise power of the transmitter amplifier PN,TX = 200 fW. Calculate the SNR of the transmit signal SNRS in dB! (1 point)
(d) Provide the SNR of the transmit signal SNRS in linear scale! (1 point)
(e) Provide a formula for converting gain/ratio from linear (gLIN) to logarithmic scale (GLOG) and vice versa! (1 point)
(f) How does SNRS change when the power of the transmitter amplifier is reduced to the linear factor gPA = 10? Provide the value of SNRS in linear scale! (1 point)
(g) Choose the parameters frequency f and distance d such that the channel loss is approximately LD = -50 dB. Assume that the noise power of the channel at the receiver PN,CH = 2.5 nW. Provide the corresponding noise power level LN,CH in dBm and the SNR SNRR in dB! (1 point)
(h) Calculate the noise power of the transmitter amplifier PN,TX, weighted with the channel attenuation LD in nW! (1 point)
(i) Add this power, taking into account the channel attenuation LD in the linear range (sum: PΣ)! (1 point)
(j) Calculate the SNR SNRR with the power level LR = -40 dBm and the sum of the noise powers! (1 point)
(k) Assume that the signal PR = PS * gTX * 10^(LD/10dB) is noise-free (PN,TX = PN,CH = 0). Provide an expression for the noise power of the output signal PN,OUT in terms of PN,RX1 and PN,RX2! (1 point)
(l) Provide a formula for the SNR SNROUT using the result of the previous task! (1 point)
(m) Assume that f = 500 MHz, PS = 12 mW, d = 0.1 km, linear gains gTX = gRX1 = gRX2 = 1, and no noise are present. Increase the noise power PN,RX1. Describe your observation of the SNR! (1 point)
(n) Increase the noise power PN,CH. Describe your observation of the SNR! (1 point)
(o) Explain whether the rule SNRIN >= SNRS >= SNRR >= SNROUT is valid! (1 point)
(p) Configure the noise powers in the simulation such that SNRR is significantly different from SNROUT. Describe how the ratio of the SNR changes when you increase gLNA! (1 point)
(q) Explain what happens to the ratio of the two SNR when gRX1 -> infinity! (1 point)
"""

def run_tu_dresden_enrichment(project_id="tu_dresden_communications", config_path="config.json"):
    print(f"=== Processing TU Dresden Communications Exercise Sheet 1 (Project: '{project_id}') ===")
    
    db_path = Path("database") / f"{project_id}.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create SQLite schema
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE,
            filename TEXT,
            title TEXT,
            year INTEGER,
            zoom_snippet TEXT,
            extracted_text TEXT,
            is_ocr INTEGER,
            is_embedded INTEGER DEFAULT 0,
            processed_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS langextract_extractions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER,
            preset TEXT,
            text_span TEXT,
            start_char INTEGER,
            end_char INTEGER,
            attributes TEXT,
            provider TEXT,
            extracted_at TEXT,
            FOREIGN KEY(article_id) REFERENCES articles(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enrichments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER UNIQUE,
            summary TEXT,
            topics TEXT,
            turkish_title TEXT,
            turkish_summary TEXT,
            sft_qa TEXT,
            dpo_pairs TEXT,
            tr_sft_qa TEXT,
            tr_dpo_pairs TEXT,
            processed_at TEXT,
            FOREIGN KEY (article_id) REFERENCES articles(id)
        )
    """)
    conn.commit()

    # 1. Insert Exercise Sheet Article
    from datetime import datetime
    now_iso = datetime.now().isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO articles (file_path, filename, title, year, zoom_snippet, extracted_text, is_ocr, processed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "tu_dresden_exercise_sheet_1.pdf",
        "tu_dresden_exercise_sheet_1.pdf",
        "TU Dresden - Exercise Sheet 1: Signal Theory and LTI-Systems",
        2026,
        "TU Dresden Lab Work Communications Exercise Sheet 1",
        EXERCISE_SHEET_TEXT,
        0,
        now_iso
    ))
    conn.commit()
    article_id = cursor.lastrowid

    # 2. Run LangExtract Grounded Extraction
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["db_path"] = str(db_path)
    cfg["project_id"] = project_id

    engine = LangExtractEngine(cfg)
    lx_result = engine.extract_grounded_entities(
        text=EXERCISE_SHEET_TEXT,
        schema_preset="engineering_exercise_sheet"
    )

    entities = lx_result.get("entities", [])
    print(f"  [LangExtract] Extracted {len(entities)} grounded entity spans with preset 'engineering_exercise_sheet'.")

    for ent in entities:
        stext = ent.get("text_span", "")
        start = ent.get("start_char", 0)
        end = ent.get("end_char", len(stext))
        attr = json.dumps(ent.get("attributes", {}), ensure_ascii=False)

        cursor.execute("""
            INSERT INTO langextract_extractions (article_id, preset, text_span, start_char, end_char, attributes, provider, extracted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (article_id, "engineering_exercise_sheet", stext, start, end, attr, lx_result.get("provider", "ollama"), now_iso))
    conn.commit()

    # 3. Generate Interactive HTML Visualizer Report
    vis_dir = Path("exports") / project_id / "langextract_visualizations"
    vis_dir.mkdir(parents=True, exist_ok=True)
    out_html = vis_dir / "exercise_sheet_1_grounded.html"
    engine.generate_visualization_html(EXERCISE_SHEET_TEXT, lx_result, str(out_html))
    print(f"  [Visualizer] Interactive HTML report created -> {out_html}")

    # 4. Generate SFT Q&A and DPO Preference Pairs for TU Dresden Communications Course
    sft_qa = [
        {
            "question": "Calculate the effective power in mW and power level in dBm for a sinusoidal voltage signal with amplitude A = 2 V across a coaxial wave resistance R = 50 Ω.",
            "answer": "The effective (RMS) voltage of a sinusoidal signal is V_rms = A / sqrt(2) = 2 / sqrt(2) = sqrt(2) V.\nThe average power is P = V_rms^2 / R = (sqrt(2))^2 / 50 = 2 / 50 = 0.04 W = 40 mW.\nConverting to logarithmic power level in dBm: L = 10 * log10(P / 1 mW) = 10 * log10(40) = 10 * 1.60206 ≈ 16.02 dBm."
        },
        {
            "question": "How does doubling the signal frequency affect the total power of a voltage signal across a coaxial transmission line?",
            "answer": "Doubling the signal frequency has NO effect on the total power of the voltage signal. The signal power P = V_rms^2 / R depends exclusively on the RMS voltage magnitude V_rms and the load resistance R, which are independent of signal frequency f."
        },
        {
            "question": "For a transmitter with output power P_S = 250 mW and linear power amplifier gain g_TX = 16, calculate the amplified transmit power P_{S,G} in Watts and power level L_{S,G} in dBm.",
            "answer": "1. Linear Amplified Power: P_{S,G} = P_S * g_TX = 250 mW * 16 = 4000 mW = 4.0 W.\n2. Power Level in dBm: L_{S,G} = 10 * log10(4000 mW / 1 mW) = 10 * (log10(4) + log10(1000)) = 10 * (0.60206 + 3) ≈ 36.02 dBm."
        },
        {
            "question": "Explain Friis formula for cascaded noise figure and why Low Noise Amplifier (LNA) gain g_LNA is critical for total receiver SNR.",
            "answer": "According to Friis formula for noise figure in cascaded systems, the total noise factor F_total = F_1 + (F_2 - 1)/g_1 + (F_3 - 1)/(g_1 * g_2) + ... where g_1 is the linear gain of the first stage (LNA). A high LNA gain g_LNA (g_RX1) suppresses the noise contributions of all subsequent receiver stages (mixers, secondary amplifiers, ADCs), ensuring that the overall SNR_OUT approaches SNR_R."
        }
    ]

    tr_sft_qa = [
        {
            "question": "Empedansı R = 50 Ω olan koaksiyel hat üzerinde genliği A = 2 V olan sinüsoidal bir gerilim sinyalinin ortalama gücünü mW ve güç seviyesini dBm cinsinden hesaplayınız.",
            "answer": "Sinüsoidal sinyalin etkin (RMS) gerilimi V_rms = A / sqrt(2) = 2 / sqrt(2) = sqrt(2) V olarak bulunur.\nOrtalama güç P = V_rms^2 / R = (sqrt(2))^2 / 50 = 2 / 50 = 0.04 W = 40 mW olur.\ndBm cinsinden güç seviyesi L = 10 * log10(P / 1 mW) = 10 * log10(40) = 10 * 1.60206 ≈ 16.02 dBm olarak hesaplanır."
        },
        {
            "question": "Sinyal frekansının iki katına çıkarılması iletken hattaki sinyal gücünü nasıl etkiler? Nedeniyle açıklayınız.",
            "answer": "Sinyal frekansının iki katına çıkarılması ortalama sinyal gücünü DEĞİŞTİRMEZ. Güç formülü P = V_rms^2 / R yalnızca RMS gerilim genliğine ve hat empedansına bağlıdır; frekanstan bağımsızdır."
        },
        {
            "question": "Verici gücü P_S = 250 mW ve doğrusal yükselteç kazancı g_TX = 16 olan bir sistemde yükseltilmiş verici gücünü P_{S,G} (Watt) ve dBm cinsinden seviyesini L_{S,G} hesaplayınız.",
            "answer": "1. Doğrusal Güç: P_{S,G} = P_S * g_TX = 250 mW * 16 = 4000 mW = 4.0 W.\n2. dBm Güç Seviyesi: L_{S,G} = 10 * log10(4000 mW / 1 mW) = 10 * (0.60206 + 3) ≈ 36.02 dBm."
        },
        {
            "question": "Ardışık (kaskad) alıcı sistemlerinde Friis gürültü formülüne göre Düşük Gürültülü Yükselteç (LNA) kazancının g_LNA toplam SNR_OUT üzerindeki etkisini açıklayınız.",
            "answer": "Friis gürültü formülüne göre kaskad katların toplam gürültü faktörü F_toplam = F_1 + (F_2 - 1)/g_1 + (F_3 - 1)/(g_1 * g_2) şeklindedir. İlk kat olan LNA'nın yüksek doğrusal kazancı g_1 (g_LNA), kendinden sonra gelen karıştırıcı (mixer), filtre ve ikinci derece yükselteçlerin gürültü katkılarını bastırır. Böylece toplam çıkış SNR_OUT, alıcı girişindeki SNR_R değerine yaklaşır."
        }
    ]

    dpo_pairs = [
        {
            "question": "How does signal power change when the voltage amplitude A is doubled from 2V to 4V on a 50 Ω line?",
            "chosen": "When amplitude A is doubled (from 2V to 4V), the RMS voltage doubles (V_rms = 4/sqrt(2) = 2.828 V). Since power P = V_rms^2 / R is proportional to the square of amplitude (P ∝ A^2), quadrupling occurs: P = (2.828)^2 / 50 = 8 / 50 = 0.16 W = 160 mW (an increase of +6.02 dB).",
            "rejected": "When amplitude is doubled, power doubles from 40 mW to 80 mW because power is directly proportional to voltage P = V/R."
        }
    ]

    tr_dpo_pairs = [
        {
            "question": "50 Ω hat üzerinde gerilim genliği A 2V'den 4V'a çıkarıldığında sinyal gücü nasıl değişir?",
            "chosen": "Genlik iki katına çıktığında RMS gerilim iki katına çıkar. Güç P = V_rms^2 / R genliğin karesiyle orantılı olduğu için (P ∝ A^2) güç 4 katına çıkar: P = (2.828)^2 / 50 = 0.16 W = 160 mW olur (güç seviyesi +6.02 dB artar).",
            "rejected": "Genlik iki katına çıktığında güç de iki katına çıkar ve 40 mW'tan 80 mW'a yükselir çünkü güç P = V/R formülüyle doğru orantılıdır."
        }
    ]

    cursor.execute("""
        INSERT OR REPLACE INTO enrichments (
            article_id, summary, topics, turkish_title, turkish_summary, sft_qa, dpo_pairs, tr_sft_qa, tr_dpo_pairs, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        article_id,
        "TU Dresden Lab Work Communications Exercise Sheet 1 covering Signal Power, dBm conversions, Amplifier & Channel Loss, and Signal-to-Noise Ratio (SNR).",
        json.dumps(["Signal Power", "dBm Conversion", "Channel Loss", "SNR", "LTI Systems", "GNURadio"]),
        "TU Dresden - Alıştırma Sayfası 1: Sinyal Teorisi ve LTI Sistemleri",
        "TU Dresden İletişim Sistemleri Laboratuvarı Alıştırma Sayfası 1: Sinyal Gücü, dBm Çevrimleri, Yükselteç ve Kanal Kaybı ile Sinyal-Gürültü Oranı (SNR) hesaplamaları.",
        json.dumps(sft_qa, ensure_ascii=False),
        json.dumps(dpo_pairs, ensure_ascii=False),
        json.dumps(tr_sft_qa, ensure_ascii=False),
        json.dumps(tr_dpo_pairs, ensure_ascii=False),
        now_iso
    ))
    conn.commit()

    # 5. Export Datasets (JSONL & Parquet)
    from pipeline.dataset_builder import DatasetBuilder
    builder = DatasetBuilder(config_path=config_path)
    builder.db_path = str(db_path)
    builder.export_dir = Path("exports") / project_id
    builder.export_dir.mkdir(parents=True, exist_ok=True)
    builder.export_datasets()

    conn.close()
    print(f"✅ TU Dresden Communications Exercise Sheet 1 enrichment complete!")
    print(f"   Export Directory: exports/{project_id}/")

if __name__ == "__main__":
    run_tu_dresden_enrichment()
