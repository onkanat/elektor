Connecting to OpenAI-compatible server at: https://ollama.com/v1
Mode: Ollama Cloud
API key: 3c4f...83og (len=57)
Loaded cloud models from cloud.txt: ['gpt-oss:120b', 'nemotron-3-nano:30b', 'minimax-m3', 'gpt-oss:20b', 'nemotron-3-ultra', 'gemma4:31b', 'nemotron-3-super']
Starting benchmark for 7 generation models...

[1/7] Benchmarking: gpt-oss:120b
  Response    : A resistor limits the flow of electric current in a circuit, converting excess electrical energy into heat according to Ohm’s law.
  Prompt Toks : 77
  Gen Toks    : 102
  Eval Speed  : 54.34 tok/s
  Wall Time   : 1.877 s

[2/7] Benchmarking: nemotron-3-nano:30b
  Response    : A resistor limits the flow of electric current in a circuit by providing a specific amount of opposition to the voltage.
  Prompt Toks : 28
  Gen Toks    : 129
  Eval Speed  : 130.03 tok/s
  Wall Time   : 0.992 s

[3/7] Benchmarking: minimax-m3
  Response    : A resistor is a passive electronic component that restricts the flow of electric current in a circuit, dissipating the excess energy as heat in order to control voltage and current levels.
  Prompt Toks : 186
  Gen Toks    : 51
  Eval Speed  : 42.93 tok/s
  Wall Time   : 1.188 s

[4/7] Benchmarking: gpt-oss:20b
  Response    : A resistor limits the flow of electric current in a circuit by providing resistance, thereby controlling voltage and current levels.
  Prompt Toks : 77
  Gen Toks    : 131
  Eval Speed  : 57.78 tok/s
  Wall Time   : 2.267 s

[5/7] Benchmarking: nemotron-3-ultra
  Response    : A resistor opposes the flow of electric current, converting electrical energy into heat to control voltage and current levels within a circuit.
  Prompt Toks : 28
  Gen Toks    : 60
  Eval Speed  : 15.41 tok/s
  Wall Time   : 3.893 s

[6/7] Benchmarking: gemma4:31b
  Response    : A resistor limits the flow of electrical current in a circuit to protect components or control voltage levels.
  Prompt Toks : 23
  Gen Toks    : 20
  Eval Speed  : 18.15 tok/s
  Wall Time   : 1.102 s

[7/7] Benchmarking: nemotron-3-super
  Response    : A resistor limits the flow of electric current in a circuit by converting electrical energy into heat.
  Prompt Toks : 28
  Gen Toks    : 113
  Eval Speed  : 6.65 tok/s
  Wall Time   : 16.989 s

================================================================================
BENCHMARK REPORT SUMMARY
================================================================================

| Model | Prompt Toks | Gen Toks | Eval (t/s) | Wall (s) | Status |
|---|---|---|---|---|---|
| `nemotron-3-nano:30b` | 28 | 129 | 130.03 | 0.99 | ✅ |
| `gpt-oss:20b` | 77 | 131 | 57.78 | 2.27 | ✅ |
| `gpt-oss:120b` | 77 | 102 | 54.34 | 1.88 | ✅ |
| `minimax-m3` | 186 | 51 | 42.93 | 1.19 | ✅ |
| `gemma4:31b` | 23 | 20 | 18.15 | 1.10 | ✅ |
| `nemotron-3-ultra` | 28 | 60 | 15.41 | 3.89 | ✅ |
| `nemotron-3-super` | 28 | 113 | 6.65 | 16.99 | ✅ |
