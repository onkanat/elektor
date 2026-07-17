import time
import json
import argparse
import sys
import ollama

def benchmark_models(host, prompt):
    print(f"Connecting to Ollama server at: {host}...")
    try:
        client = ollama.Client(host=host, timeout=180.0)
        models_list = client.list().models
    except Exception as e:
        print(f"Error connecting to Ollama server: {e}")
        sys.exit(1)
        
    if not models_list:
        print("No models found on the server.")
        return
        
    print(f"Found {len(models_list)} models on the server.")
    
    # Filter out embedding models (e.g. nomic-embed-text)
    # Embedding-only models typically have only "embedding" or don't support completion
    chat_models = []
    for m in models_list:
        name = m.model
        # Check details/capabilities if available
        capabilities = getattr(m, 'capabilities', [])
        # Fallback check if capabilities is empty: skip nomic
        if 'nomic' in name.lower() or (capabilities and 'embedding' in capabilities and len(capabilities) == 1):
            print(f"  Skipping embedding-only model: {name}")
            continue
        chat_models.append(m)
        
    print(f"Starting benchmark for {len(chat_models)} generation models...")
    
    results = []
    
    for idx, model in enumerate(chat_models):
        name = model.model
        size_gb = getattr(model, 'size', 0) / (1024**3)
        details = getattr(model, 'details', None)
        param_size = getattr(details, 'parameter_size', 'N/A') if details else 'N/A'
        
        print(f"\n[{idx+1}/{len(chat_models)}] Benchmarking: {name} (Params: {param_size}, Size: {size_gb:.2f} GB)")
        
        # Step 1: Force unload model first (by sending a keep_alive=0 call)
        print("  Ensuring model is unloaded from server memory...")
        try:
            client.generate(model=name, prompt="", keep_alive=0)
        except Exception:
            pass
        
        # Settle time
        time.sleep(3)
        
        # Step 2: Measure cold load and inference
        print(f"  Running benchmark query: '{prompt}'")
        try:
            start_wall = time.time()
            response = client.generate(
                model=name,
                prompt=prompt,
                keep_alive=0,  # Unload model immediately after completion to free memory
                options={
                    "temperature": 0.3,
                    "num_predict": 150 # Bound output to prevent infinite loops
                }
            )
            wall_time = time.time() - start_wall
            
            # Extract high-resolution metrics from response
            load_duration = response.get("load_duration", 0) / 1e9          # ns to s
            prompt_eval_count = response.get("prompt_eval_count", 0)
            prompt_eval_duration = response.get("prompt_eval_duration", 0) / 1e9 # ns to s
            eval_count = response.get("eval_count", 0)
            eval_duration = response.get("eval_duration", 0) / 1e9          # ns to s
            
            prompt_tps = prompt_eval_count / prompt_eval_duration if prompt_eval_duration > 0 else 0
            eval_tps = eval_count / eval_duration if eval_duration > 0 else 0
            
            # Print response snippet
            content = response.get("response", "").strip().replace('\n', ' ')
            snippet = content[:80] + "..." if len(content) > 80 else content
            print(f"  Snippet: {snippet}")
            print(f"  Cold Load Time : {load_duration:.3f} s")
            print(f"  Prompt Eval    : {prompt_eval_count} tokens in {prompt_eval_duration:.3f} s ({prompt_tps:.2f} tok/s)")
            print(f"  Generation     : {eval_count} tokens in {eval_duration:.3f} s ({eval_tps:.2f} tok/s)")
            print(f"  Wall Time      : {wall_time:.3f} s")
            
            results.append({
                "model": name,
                "param_size": param_size,
                "size_gb": size_gb,
                "load_time_sec": load_duration,
                "prompt_eval_tps": prompt_tps,
                "generation_tps": eval_tps,
                "wall_time_sec": wall_time,
                "status": "Success"
            })
            
        except Exception as e:
            print(f"  Error benchmarking {name}: {e}")
            results.append({
                "model": name,
                "param_size": param_size,
                "size_gb": size_gb,
                "load_time_sec": 0,
                "prompt_eval_tps": 0,
                "generation_tps": 0,
                "wall_time_sec": 0,
                "status": f"Failed: {str(e)}"
            })
            
        # Give remote server some settle time between models
        time.sleep(3)
        
    print("\n" + "="*80)
    print("BENCHMARK REPORT SUMMARY")
    print("="*80)
    
    # Sort results by generation tokens per second descending
    successful_results = [r for r in results if r["status"] == "Success"]
    failed_results = [r for r in results if r["status"] != "Success"]
    
    sorted_results = sorted(successful_results, key=lambda x: x["generation_tps"], reverse=True) + failed_results
    
    # Output Markdown Table
    print("\n| Model Name | Parameters | Size (GB) | Cold Load (s) | Prompt Speed (t/s) | Eval Speed (t/s) | Wall Time (s) | Status |")
    print("|---|---|---|---|---|---|---|---|")
    for r in sorted_results:
        if r["status"] == "Success":
            print(f"| `{r['model']}` | {r['param_size']} | {r['size_gb']:.2f} | {r['load_time_sec']:.2f}s | {r['prompt_eval_tps']:.2f} | {r['generation_tps']:.2f} | {r['wall_time_sec']:.2f}s | Success |")
        else:
            print(f"| `{r['model']}` | {r['param_size']} | {r['size_gb']:.2f} | N/A | N/A | N/A | N/A | {r['status']} |")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ollama Server Model Benchmarker")
    parser.add_argument("--host", type=str, default="http://192.168.1.14:11434", help="Ollama server URL")
    parser.add_argument("--prompt", type=str, 
                        default="Explain what a resistor does in exactly one sentence.", 
                        help="Benchmark prompt to send to all models")
    args = parser.parse_args()
    
    benchmark_models(args.host, args.prompt)
